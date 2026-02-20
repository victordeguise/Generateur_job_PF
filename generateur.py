#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Générateur de Jobs Automatisé - Optimisation & Déploiement FM

Fonctionnalités :
    - Génération automatique de jobs .bat/.cmd à partir de fichiers source
    - Routage intelligent JOB/SCRIPT selon l'extension
    - Comparaison HTML entre versions de fichiers
    - Transfert sur serveurs avec horodatage et rollback
    - Intégration Git pour détection automatique des fichiers modifiés
    - Mode dry-run, sauvegarde, et historique des opérations
"""

import os
import shutil
import difflib
from datetime import datetime
import subprocess
import sys
import logging
import json
import hashlib
import re
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════
#                   CONFIGURATION DU LOGGING
# ═══════════════════════════════════════════════════════════════

LOG_FILE = "generateur_debug.log"
CONFIG_FILE = "config_generateur.json"
HISTORY_FILE = "historique_operations.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#                   GESTION DES DÉPENDANCES
# ═══════════════════════════════════════════════════════════════

def install_and_import(package: str, import_name: str = None):
    """
    Installe un package Python s'il n'est pas disponible, puis l'importe.
    """
    if import_name is None:
        import_name = package
    try:
        return __import__(import_name)
    except ImportError:
        logger.info(f"Installation du package manquant : {package}...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Échec de l'installation de {package}: {e}")
            raise
        return __import__(import_name)


# Installation des dépendances
git_module = install_and_import("gitpython", "git")
install_and_import("chardet")
install_and_import("questionary")
install_and_import("rich")

# Imports après installation garantie
import chardet
import questionary
from pathlib import Path
from git import Repo, InvalidGitRepositoryError, NoSuchPathError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# ═══════════════════════════════════════════════════════════════
#                   CHEMIN RACINE (Compatible .EXE)
# ═══════════════════════════════════════════════════════════════

if getattr(sys, 'frozen', False):
    SCRIPT_PATH = Path(sys.executable).parent.absolute()
else:
    SCRIPT_PATH = Path(__file__).parent.absolute()


# ═══════════════════════════════════════════════════════════════
#                   ROUTAGE INTELLIGENT JOB / SCRIPT
# ═══════════════════════════════════════════════════════════════

def determiner_dossier_serveur(nom_fichier: str, chemin_relatif_git: str = "") -> str:
    """
    Détermine le dossier de destination sur le serveur (job ou script).

    Logique de routage :
        1. Si le chemin Git contient déjà 'script' ou 'job', on le respecte
        2. Sinon, on se base sur l'extension :
           - .cmd → script
           - .bat → job
        3. Fichiers spéciaux (_appli, init_var) → param

    Args:
        nom_fichier: Nom du fichier (ex: fm_kpi.cmd, jfm1aa10.bat)
        chemin_relatif_git: Chemin relatif dans le dépôt Git
                            (ex: script/fm_kpi.cmd, job/sg_xxx/jfm1aa10.bat)

    Returns:
        Dossier de destination : 'job', 'script' ou 'param'

    Examples:
        >>> determiner_dossier_serveur("fm_kpi.cmd")
        'script'
        >>> determiner_dossier_serveur("jfm1aa10.bat")
        'job'
        >>> determiner_dossier_serveur("fm1_appli.bat")
        'param'
        >>> determiner_dossier_serveur("jfm1aa10.bat", "job/jfm1aa/jfm1aa10.bat")
        'job'
        >>> determiner_dossier_serveur("fm_kpi.cmd", "script/fm_kpi.cmd")
        'script'
    """
    nom_lower = nom_fichier.lower()
    chemin_lower = chemin_relatif_git.lower().replace("\\", "/")

    # ──── Cas 1 : Fichiers spéciaux → param ────
    if '_appli' in nom_lower or 'init_var' in nom_lower:
        logger.info(f"Routage {nom_fichier} → param (fichier spécial)")
        return 'param'

    # ──── Cas 2 : Le chemin Git indique déjà le dossier ────
    if chemin_lower:
        # Extraire le premier segment du chemin
        segments = [s for s in chemin_lower.split('/') if s]
        if segments:
            premier_segment = segments[0]
            if premier_segment in ('script', 'job', 'param'):
                logger.info(
                    f"Routage {nom_fichier} → {premier_segment} "
                    f"(déduit du chemin Git: {chemin_relatif_git})"
                )
                return premier_segment

    # ──── Cas 3 : Se baser sur l'extension ────
    if nom_lower.endswith('.cmd'):
        logger.info(f"Routage {nom_fichier} → script (extension .cmd)")
        return 'script'
    elif nom_lower.endswith('.bat'):
        logger.info(f"Routage {nom_fichier} → job (extension .bat)")
        return 'job'

    # ──── Cas 4 : Défaut ────
    logger.warning(
        f"Routage {nom_fichier} → job (par défaut, extension non reconnue)"
    )
    return 'job'


def construire_chemin_serveur(
    server: str,
    nom_chaine: str,
    nom_fichier: str,
    chemin_relatif_git: str = "",
    sous_dossier: str = ""
) -> str:
    """
    Construit le chemin complet sur le serveur.

    Args:
        server: Adresse du serveur
        nom_chaine: Nom de l'application (fm, fm1, fm4...)
        nom_fichier: Nom du fichier
        chemin_relatif_git: Chemin relatif dans Git (optionnel)
        sous_dossier: Sous-dossier spécifique (ex: jfm1aa pour les sous-groupes)

    Returns:
        Chemin UNC complet (ex: //serveur/prod/fm/script/fm_kpi.cmd)
    """
    dossier = determiner_dossier_serveur(nom_fichier, chemin_relatif_git)

    if sous_dossier:
        chemin = f"//{server}/prod/{nom_chaine}/{dossier}/{sous_dossier}/{nom_fichier}"
    else:
        chemin = f"//{server}/prod/{nom_chaine}/{dossier}/{nom_fichier}"

    logger.info(f"Chemin serveur construit: {chemin}")
    return chemin


def extraire_sous_dossier(chemin_relatif_git: str, nom_fichier: str) -> str:
    """
    Extrait le sous-dossier intermédiaire du chemin Git.

    Par exemple, pour 'job/jfm1aa/jfm1aa10.bat', extrait 'jfm1aa'.
    Pour 'script/fm_kpi.cmd', retourne '' (pas de sous-dossier).

    Args:
        chemin_relatif_git: Chemin relatif dans le dépôt
        nom_fichier: Nom du fichier

    Returns:
        Sous-dossier intermédiaire ou chaîne vide
    """
    chemin_normalise = chemin_relatif_git.replace("\\", "/")
    segments = [s for s in chemin_normalise.split('/') if s]

    # On retire le premier segment (job/script/param) et le dernier (le fichier)
    if len(segments) > 2:
        # Il y a des segments intermédiaires
        sous_dossier = "/".join(segments[1:-1])
        logger.info(f"Sous-dossier extrait: {sous_dossier}")
        return sous_dossier

    return ""


# ═══════════════════════════════════════════════════════════════
#                   DATA CLASSES DE CONFIGURATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class JobConfig:
    """Configuration pour la génération d'un job."""
    nom_job: str
    input_path: str
    output_path: str
    date_jour: str
    phase_depart: int = 0
    username: str = ""

    def __post_init__(self):
        if not self.username:
            self.username = os.getenv('USERNAME', 'UNKNOWN')


@dataclass
class TransferResult:
    """Résultat d'un transfert de fichier."""
    fichier: str
    succes: bool
    message: str
    dossier_destination: str = ""  # NOUVEAU: job, script ou param
    chemin_serveur: str = ""       # NOUVEAU: chemin complet sur le serveur
    horodatage_ancien: str = ""
    checksum_avant: str = ""
    checksum_apres: str = ""


@dataclass
class AppConfig:
    """Configuration globale de l'application."""
    git_path: str = ""
    derniere_application: str = ""
    dernier_serveur: str = ""
    theme: str = "default"
    dry_run: bool = False
    historique: List[Dict] = field(default_factory=list)

    APPLIS_VALIDES: List[str] = field(default_factory=lambda: [
        "fm", "fm0", "fm1", "fm2", "fm3", "fm4",
        "fm5", "fm6", "fm7", "fm8", "fm9"
    ])

    SERVEURS: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        "fm4": {
            "recette fm4": "pfadc6fm4app01r",
            "prod fm4": "pfadc2fm4app01p"
        },
        "default": {
            "recette": "pfovhvrfmxapp01",
            "prod": "pfovhvpfmxapp01"
        }
    })

    def get_serveurs(self, nom_chaine: str) -> Dict[str, str]:
        return self.SERVEURS.get(nom_chaine, self.SERVEURS["default"])


# ═══════════════════════════════════════════════════════════════
#                   GESTION DE LA CONFIGURATION
# ═══════════════════════════════════════════════════════════════

class ConfigManager:
    """Gestionnaire de configuration persistante."""

    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = config_path
        self.config = self._load()

    def _load(self) -> AppConfig:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return AppConfig(
                    git_path=data.get("git_path", ""),
                    derniere_application=data.get("derniere_application", ""),
                    dernier_serveur=data.get("dernier_serveur", ""),
                    theme=data.get("theme", "default"),
                    dry_run=data.get("dry_run", False)
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Fichier de configuration corrompu: {e}")
        return AppConfig()

    def save(self):
        data = {
            "git_path": self.config.git_path,
            "derniere_application": self.config.derniere_application,
            "dernier_serveur": self.config.dernier_serveur,
            "theme": self.config.theme,
            "dry_run": self.config.dry_run
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Impossible de sauvegarder la configuration: {e}")

    @property
    def git_path(self) -> str:
        return self.config.git_path

    @git_path.setter
    def git_path(self, value: str):
        self.config.git_path = value
        self.save()


# ═══════════════════════════════════════════════════════════════
#                   HISTORIQUE DES OPÉRATIONS
# ═══════════════════════════════════════════════════════════════

class HistoryManager:
    """Gestionnaire d'historique des opérations effectuées."""

    def __init__(self, history_path: str = HISTORY_FILE):
        self.history_path = history_path
        self.entries: List[Dict] = self._load()

    def _load(self) -> List[Dict]:
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Historique corrompu, création d'un nouveau.")
        return []

    def _save(self):
        try:
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Impossible de sauvegarder l'historique: {e}")

    def ajouter(self, operation: str, details: Dict):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "utilisateur": os.getenv('USERNAME', 'UNKNOWN'),
            **details
        }
        self.entries.append(entry)
        self._save()
        logger.info(f"Historique: {operation} - {details.get('fichier', 'N/A')}")

    def afficher(self, nb_entries: int = 20):
        table = Table(title="Historique des opérations", box=box.ROUNDED, show_lines=True)
        table.add_column("Date", style="cyan", width=20)
        table.add_column("Opération", style="green", width=15)
        table.add_column("Fichier", style="white", width=25)
        table.add_column("Dossier", style="magenta", width=10)
        table.add_column("Détails", style="yellow", width=35)

        for entry in self.entries[-nb_entries:]:
            timestamp = entry.get("timestamp", "N/A")[:19]
            operation = entry.get("operation", "N/A")
            fichier = entry.get("fichier", "N/A")
            dossier = entry.get("dossier_destination", "")
            details = entry.get("resultat", entry.get("serveur", ""))
            table.add_row(timestamp, operation, fichier, dossier, str(details))

        console.print(table)

    def chercher(self, terme: str) -> List[Dict]:
        resultats = []
        terme_lower = terme.lower()
        for entry in self.entries:
            if any(terme_lower in str(v).lower() for v in entry.values()):
                resultats.append(entry)
        return resultats


# ═══════════════════════════════════════════════════════════════
#                   FONCTIONS UTILITAIRES
# ═══════════════════════════════════════════════════════════════

def calculer_checksum(filepath: str) -> str:
    hash_md5 = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except FileNotFoundError:
        return "FICHIER_INTROUVABLE"
    except IOError as e:
        logger.error(f"Erreur de lecture pour le checksum: {e}")
        return "ERREUR_LECTURE"


def detect_encoding(file_path: str) -> str:
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            result = chardet.detect(raw_data)
            encoding = result.get('encoding', 'utf-8')
            return encoding or 'utf-8'
    except IOError:
        return 'utf-8'


def validation_nom_job(text: str) -> bool | str:
    if not text:
        return "Le nom ne peut pas être vide"
    if not text.lower().endswith(('.bat', '.cmd')):
        return "Le job doit finir par .bat ou .cmd"
    caracteres_interdits = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    if any(char in text for char in caracteres_interdits):
        return f"Le nom contient des caractères interdits"
    if len(text) < 5:
        return "Le nom du job est trop court (minimum 5 caractères)"
    return True


def afficher_resume_operation(
    operation: str,
    fichiers: List[str],
    serveur: str = "",
    branche: str = ""
):
    """Affiche un résumé avec le dossier de destination pour chaque fichier."""
    table = Table(
        title=f"Résumé - {operation}",
        box=box.DOUBLE_EDGE,
        show_lines=True,
        title_style="bold cyan"
    )
    table.add_column("Propriété", style="bold white", width=20)
    table.add_column("Valeur", style="green", width=50)

    table.add_row("Opération", operation)
    table.add_row("Nb fichiers", str(len(fichiers)))
    if serveur:
        table.add_row("Serveur", serveur)
    if branche:
        table.add_row("Branche", branche)
    table.add_row("Date", datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
    table.add_row("Utilisateur", os.getenv('USERNAME', 'UNKNOWN'))

    console.print(table)

    # ──── Tableau détaillé avec routage ────
    if fichiers:
        file_table = Table(
            title="Fichiers et destinations",
            box=box.SIMPLE,
            show_lines=False
        )
        file_table.add_column("#", style="dim", width=4)
        file_table.add_column("Fichier", style="white", width=35)
        file_table.add_column("Extension", style="cyan", width=6)
        file_table.add_column("Dossier serveur", style="bold magenta", width=10)

        for i, f in enumerate(fichiers, 1):
            nom = os.path.basename(f)
            ext = Path(nom).suffix or "N/A"
            dossier = determiner_dossier_serveur(nom, f)
            # Couleur selon le dossier
            dossier_style = {
                'script': '[bold yellow]SCRIPT[/bold yellow]',
                'job': '[bold green]JOB[/bold green]',
                'param': '[bold blue]PARAM[/bold blue]'
            }.get(dossier, dossier)
            file_table.add_row(str(i), f, ext, dossier_style)

        console.print(file_table)
        console.print()


def extraire_info_job(nom_job: str) -> Dict[str, str]:
    """
    Extrait les informations structurelles d'un nom de job.

    Returns:
        Dictionnaire avec 'fm', 'sg', 'folder'
    """
    nom_lower = nom_job.lower()
    folder = determiner_dossier_serveur(nom_job).upper()

    if "_" in nom_job and nom_job.index("_") <= 3:
        fm = nom_job[:nom_job.index("_")]
        sg = ""
    else:
        fm = nom_lower[1:4] if len(nom_lower) > 4 else nom_lower[:3]
        sg = nom_lower[:6] if len(nom_lower) >= 6 else ""

    return {"fm": fm, "sg": sg, "folder": folder}


# ═══════════════════════════════════════════════════════════════
#                   FONCTIONS GIT
# ═══════════════════════════════════════════════════════════════

class GitManager:
    """Gestionnaire des opérations Git."""

    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager

    def is_valid_git_path(self, path: str) -> bool:
        try:
            repo = Repo(path)
            if repo.bare:
                return False
            return True
        except (InvalidGitRepositoryError, NoSuchPathError):
            return False
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la vérification Git: {e}")
            return False

    def get_git_path(self) -> Optional[str]:
        console.print("[bold cyan]🔍 Recherche du dépôt Git...[/bold cyan]")

        common_paths = [
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Projects"),
            os.path.expanduser("~/repos"),
            os.path.expanduser("~/git"),
        ]

        found_repos = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Recherche en cours...", total=None)

            for base_path in common_paths:
                if not os.path.exists(base_path):
                    continue
                try:
                    for root, dirs, _ in os.walk(base_path):
                        depth = root.replace(base_path, "").count(os.sep)
                        if depth > 4:
                            dirs.clear()
                            continue
                        dirs[:] = [
                            d for d in dirs
                            if not d.startswith('.')
                            and d not in ['node_modules', '__pycache__', 'venv', '.venv', 'env']
                        ]
                        if '.git' in os.listdir(root):
                            found_repos.append(os.path.abspath(root))
                            progress.update(task, description=f"Trouvé: {root}")
                except PermissionError:
                    continue

        if found_repos:
            console.print(f"\n[green]✅ {len(found_repos)} dépôt(s) trouvé(s)[/green]")
            choices = found_repos + ["⌨️  Entrer manuellement"]
            selected = questionary.select("Sélectionnez le dépôt:", choices=choices).ask()
            if selected != "⌨️  Entrer manuellement":
                return selected

        while True:
            git_path = questionary.path("Chemin du dépôt Git:", only_directories=True).ask()
            if git_path and self.is_valid_git_path(git_path):
                console.print("[green]✅ Chemin Git valide.[/green]")
                return git_path
            else:
                console.print("[red]❌ Chemin Git invalide.[/red]")
                if not questionary.confirm("Réessayer ?").ask():
                    return None

    def get_git_branch(self, local_repo_path: str) -> Optional[str]:
        try:
            repo = Repo(local_repo_path)
            branch_name = repo.active_branch.name
            console.print(f"🌿 Branche active: [bold green]{branch_name}[/bold green]")
            return branch_name
        except TypeError:
            commit = Repo(local_repo_path).head.commit.hexsha[:8]
            console.print(f"[yellow]⚠ HEAD détachée: {commit}[/yellow]")
            return f"detached-{commit}"
        except Exception as e:
            logger.error(f"Erreur branche: {e}")
            return None

    def get_modified_files(
        self, local_repo_path: str, develop_branch: str, base_branch: str = "master"
    ) -> List[str]:
        try:
            repo = Repo(local_repo_path)
            branches_existantes = [b.name for b in repo.branches]

            if base_branch not in branches_existantes:
                console.print(
                    f"[yellow]⚠ Branche '{base_branch}' non trouvée.[/yellow]"
                )
                base_branch = questionary.select(
                    "Branche de référence:", choices=branches_existantes
                ).ask()

            modified_files = repo.git.diff(
                base_branch, develop_branch, name_only=True
            ).split('\n')
            modified_files = [f for f in modified_files if f.strip()]

            if modified_files:
                # ──── Tableau avec routage visible ────
                table = Table(
                    title="Fichiers modifiés détectés",
                    box=box.ROUNDED,
                    show_lines=False
                )
                table.add_column("#", style="dim", width=4)
                table.add_column("Fichier", style="white", width=40)
                table.add_column("Extension", style="cyan", width=6)
                table.add_column("→ Dossier", style="bold magenta", width=10)

                for i, f in enumerate(modified_files, 1):
                    nom = os.path.basename(f)
                    ext = Path(nom).suffix or "N/A"
                    dossier = determiner_dossier_serveur(nom, f)
                    couleur = {
                        'script': '[yellow]SCRIPT[/yellow]',
                        'job': '[green]JOB[/green]',
                        'param': '[blue]PARAM[/blue]'
                    }.get(dossier, dossier)
                    table.add_row(str(i), f, ext, couleur)

                console.print(table)
            else:
                console.print("[yellow]Aucun fichier modifié.[/yellow]")

            return modified_files
        except Exception as e:
            logger.error(f"Erreur fichiers modifiés: {e}")
            return []

    def get_all_branches(self, local_repo_path: str) -> List[str]:
        try:
            return [b.name for b in Repo(local_repo_path).branches]
        except Exception:
            return []

    def get_commit_info(self, local_repo_path: str, nb_commits: int = 5) -> List[Dict]:
        try:
            repo = Repo(local_repo_path)
            return [
                {
                    "hash": c.hexsha[:8],
                    "auteur": str(c.author),
                    "date": datetime.fromtimestamp(c.committed_date).strftime('%d/%m/%Y %H:%M'),
                    "message": c.message.strip()[:80]
                }
                for c in repo.iter_commits(max_count=nb_commits)
            ]
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════
#                   GÉNÉRATEUR DE JOB
# ═══════════════════════════════════════════════════════════════

class JobGenerator:
    """Classe principale pour la génération de fichiers batch."""

    LIGNE_REM_1 = "rem ######################################################################"
    LIGNE_REM_2 = "rem #---------------------------------------------------------------------"
    LIGNE_REM_3 = "rem #--              "
    LIGNE_REM_4 = "rem ##################################################"
    LIGNE_SET_1 = "set NOMTRAIT="
    LIGNE_INF_1 = '%PERL% %PF_SKL_PROC%\\skl_infojob.pl "%PHASE%" "%NOMTRAIT%"'
    LIGNE_ERR_1 = "if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & goto ERREUR\n"
    LIGNE_ERR_2 = "if %errorlevel% GTR 1 set ERR=Erreur execution %NOMTRAIT% & goto ERREUR"
    SEND_MAIL = "call %PF_SCRIPT%\\sendMail.cmd %num_phase% %nom_job%"
    LIGNE_COPY_1 = "rem --------------------------------------------------"
    LIGNE_COPY_2 = "rem Parametres de"

    CMDS_NBERR = [
        'sort', 'ls', 'wc', 'keybuild', 'dbcheck', 'dchain',
        'export', 'pexport', 'mail', 'cat', 'uniq', 'grep',
        'join', 'sed', 'gawk', '7zip'
    ]
    CMDS_RELANCE = ['dbcheck', 'dchain', 'keybuild', 'pexport']
    CMDS_SIMPLES = [
        'if', ':', 'goto', 'set', 'type', 'mkdir',
        'rmdir', 'echo', 'find', 'ping', 'dir'
    ]

    def __init__(self):
        self.phase = 10
        self.job_name = ""
        self.nom_job2 = ""
        self.stats = {"phases_generees": 0, "commandes_traitees": 0, "erreurs": 0}

    @staticmethod
    def lire_ligne(file) -> Tuple[Optional[str], bool]:
        while True:
            line = file.readline()
            if not line:
                return None, True
            line = line.strip()
            if line:
                return line, False

    def _write_bloc_relance(self, f_out, phase_prec: int, phase_retour: int = None):
        if phase_retour is None:
            phase_retour = phase_prec
        f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{phase_prec}\n")
        f_out.write(
            f"if %errorlevel% NEQ 0 set ERR=Erreur execution "
            f"%NOMTRAIT% & set /a nberr = %nberr%+1\n"
        )
        f_out.write(f"if %nberr% EQU 1 {self.SEND_MAIL} & goto STEP{phase_retour}\n")
        f_out.write("if %nberr% GTR 1 goto ERREUR\n")
        f_out.write(f":finSTEP{phase_prec}\n\n")

    def _write_entete(self, f_out, nom_job2, date_jour, auteur, lib_job, desc_job, username):
        f_out.write('@echo off\n')
        f_out.write(f"{self.LIGNE_REM_1}\n{self.LIGNE_REM_2}\n")
        f_out.write(f"rem #-- Nom     : {nom_job2}\n")
        f_out.write(f"rem #-- Version : 1.00                   Date : {date_jour}\n")
        f_out.write(f"rem #-- Auteur  : {auteur}\n")
        f_out.write(f"{self.LIGNE_REM_2}\n")
        f_out.write(f"rem #-- Objet   : {lib_job}\nrem #--           {desc_job}\n")
        f_out.write(f"{self.LIGNE_REM_2}\nrem #-- Commentaires :\n{self.LIGNE_REM_3}\n")
        f_out.write(f"{self.LIGNE_REM_2}\nrem #--               Auteur   |      Date\n")
        f_out.write(f"{self.LIGNE_REM_2}\n{self.LIGNE_REM_3} {username}  |    {date_jour}\n")
        f_out.write(f"{self.LIGNE_REM_2}\n{self.LIGNE_REM_1}\n\n")

    def _write_initialisation(self, f_out, nom_job2):
        f_out.write("rem Chargement du .profile\n")
        f_out.write("call %0\\..\\..\\..\\skl\\param\\profile.bat\n\n")
        f_out.write("rem Récup des paramètres\nset SCHEDULE_NAME_PLAN=%1\n\n\n")
        f_out.write("rem Chargement de l'environnement\n")
        f_out.write("%PF_PERLENV%perl %0\\..\\..\\..\\skl\\param\\skl_uni_env.pl %0 > %0_env.bat\n")
        f_out.write("call %0_env.bat\ndel  %0_env.bat\n\n")
        f_out.write("rem Chargement de l'env spécif\n")
        f_out.write("if exist %PF_PARAM%\\%PF_APPLI%_appli.bat call %PF_PARAM%\\%PF_APPLI%_appli.bat\n\n")
        f_out.write(f"set nom_job={nom_job2}\n\n")
        f_out.write(f"{self.LIGNE_REM_4}\nset PHASE=00 - Début du job\n{self.LIGNE_REM_4}\n")
        f_out.write("%PERL% %PF_SKL_PROC%\\skl_debutjob.pl\n\n")
        f_out.write("%D% && cd %FM_PROG%\nrem goto STEP000\n")

    def _write_fin_job(self, f_out):
        f_out.write(f"\n{self.LIGNE_REM_4}\nset PHASE=99 - Fin du job\n{self.LIGNE_REM_4}\n")
        f_out.write("%PERL% %PF_SKL_PROC%\\skl_finjob.pl\n\ngoto FIN\n\n\n")
        f_out.write(f"{self.LIGNE_REM_4}\nrem GESTION DES ERREURS\n{self.LIGNE_REM_4}\n\n")
        f_out.write(":ERREUR\n%PERL% %PF_SKL_PROC%\\skl_message.pl F %ERRORLEVEL% %ERR%\n")
        f_out.write("copy /y %fmdata%*.%numVERSION% %D%\\prod\\%nomCHAINE%\\save\\erreur\\ >> %JOURNAL% 2>&1\n")
        f_out.write("%EXIT% 8\nexit   8\n\n:FIN\n%EXIT% 0\n\n")

    def _traiter_ligne_rem(self, f_out, line):
        parts = line.split('-')
        if len(parts) < 3:
            f_out.write(f"{line}\n")
            return
        if any(sub in line for sub in self.CMDS_NBERR):
            f_out.write("set nberr=0\n")
        f_out.write(f":STEP{self.phase}\n{self.LIGNE_REM_4}\n")
        lib_phase = parts[2].strip()
        f_out.write(f"set PHASE={self.job_name} - {self.phase} - {lib_phase}\n")
        f_out.write(f"{self.LIGNE_REM_4}\nset num_phase={self.phase}\n")
        trt = parts[1].strip()
        f_out.write(f"{self.LIGNE_SET_1}{trt}\n{self.LIGNE_INF_1}\n\n")
        self.stats["phases_generees"] += 1
        self.phase += 10

    def _traiter_cmd_fm_prog(self, f_out, line, f_in):
        phase_prec = self.phase - 10
        if any(cmd in line for cmd in self.CMDS_RELANCE):
            if "pexport" in line:
                f_out.write(f"{line}\n")
            else:
                f_out.write(f"{line} >> %JOURNAL% 2>&1 \n")
            self._write_bloc_relance(f_out, phase_prec)
        elif "pimport" in line:
            f_out.write(f"{line}\n")
            if ',' not in line:
                self._write_bloc_relance(f_out, phase_prec)
            else:
                f_out.write(f"{self.LIGNE_ERR_1}\n")
        else:
            f_out.write(f"{line}\n")
            if len(line) > 29 and line[25:29] in ["5100", "5101", "5102"]:
                f_out.write(f"{self.LIGNE_ERR_2}\n")
            else:
                f_out.write(f"{self.LIGNE_ERR_1}\n")
        self.stats["commandes_traitees"] += 1

    def _traiter_cmd_pf_exe(self, f_out, line, f_in):
        phase_prec = self.phase - 10
        f_out.write(f"{line} 2>> %JOURNAL%\n")

        if "grep" in line:
            f_out.write(f"if %errorlevel% LSS 2 goto finSTEP{phase_prec}\n")
            f_out.write(
                f"if %errorlevel% GTR 1 set ERR=Erreur execution "
                f"%NOMTRAIT% & set /a nberr = %nberr%+1\n"
            )
            f_out.write(f"if %nberr% EQU 1 {self.SEND_MAIL} & goto STEP{phase_prec}\n")
            f_out.write("if %nberr% GTR 1 goto ERREUR\n")
            f_out.write(f":finSTEP{phase_prec}\n\n")
        elif "uniq" in line:
            self._traiter_uniq(f_out, line, f_in, phase_prec)
        elif "unix2dos" in line or "touch" in line:
            f_out.write(f"{self.LIGNE_ERR_1}")
        else:
            self._write_bloc_relance(f_out, phase_prec)

        self.stats["commandes_traitees"] += 1

    def _traiter_uniq(self, f_out, line, f_in, phase_prec):
        next_line, eof = self.lire_ligne(f_in)
        if not eof and next_line and "uniq" in next_line:
            phase_inter = self.phase - 5
            f_out.write(f"if %errorlevel% EQU 0 goto STEP{phase_inter}\n")
            f_out.write(
                f"if %errorlevel% NEQ 0 set ERR=Erreur execution "
                f"%NOMTRAIT% & set /a nberr = %nberr%+1\n"
            )
            f_out.write(f"if %nberr% EQU 1 {self.SEND_MAIL} & goto STEP{phase_prec}\n")
            f_out.write("if %nberr% GTR 1 goto ERREUR\n")
            f_out.write(f":STEP{phase_inter}\n{next_line} 2>> %JOURNAL%\n")
            self._write_bloc_relance(f_out, phase_prec, phase_inter)
        else:
            self._write_bloc_relance(f_out, phase_prec)

    def _traiter_mouvement_fichier(self, f_out, line):
        parts = line.split()
        if len(parts) < 3:
            f_out.write(f"{line}\n")
            return
        mvt_type = line[:4].strip()
        f_out.write(f"{self.LIGNE_COPY_1}\n{self.LIGNE_COPY_2} {mvt_type}\n")
        f_out.write(f"echo Source :  {parts[1]} >> %JOURNAL% 2>&1\n")
        f_out.write(f"echo Cible :   {parts[2]} >> %JOURNAL% 2>&1\n")
        f_out.write(f"{self.LIGNE_COPY_1}\n\n{line} >> %JOURNAL% 2>&1\n\n")
        self.stats["commandes_traitees"] += 1

    def _traiter_boucle_for(self, f_out, line, f_in):
        f_out.write(f"{line}\n")
        if line.count('(') != line.count(')'):
            while True:
                inner, eof = self.lire_ligne(f_in)
                if eof or inner is None:
                    break
                if inner == ")":
                    f_out.write(f"{inner}\n")
                    break
                if not inner[:3].lower() == "rem":
                    f_out.write(f"{inner} 2>> %JOURNAL%\n{self.LIGNE_ERR_2}\n")
                else:
                    f_out.write(f"{inner}\n")

    def _traiter_ligne(self, f_out, line, f_in):
        line_lower = line.lower()

        if line_lower.startswith("rem"):
            if len(line) > 4 and line[4] == '-' and line.count('-') >= 2:
                self._traiter_ligne_rem(f_out, line)
            return

        if "%FM_PROG%" in line:
            self._traiter_cmd_fm_prog(f_out, line, f_in)
            return
        if "%PF_EXE" in line:
            self._traiter_cmd_pf_exe(f_out, line, f_in)
            return
        if "forfiles" in line_lower:
            f_out.write(f"{line} >> %JOURNAL% 2>&1\n\n")
            return
        if line_lower.startswith("for ") or line_lower.startswith("for%%"):
            self._traiter_boucle_for(f_out, line, f_in)
            return
        if any(line_lower.startswith(cmd) for cmd in self.CMDS_SIMPLES):
            f_out.write(f"{line}\n")
            return
        if "call" in line_lower or "program files" in line_lower:
            f_out.write(f"{line}\n{self.LIGNE_ERR_1}\n")
            self.stats["commandes_traitees"] += 1
            return
        if line_lower.startswith("move") or line_lower.startswith("copy"):
            self._traiter_mouvement_fichier(f_out, line)
            return
        if line_lower.startswith("del"):
            f_out.write(f"{line} >> %JOURNAL% 2>&1\n")
            return
        if "%PERL%" in line:
            f_out.write(f"{line} >> %JOURNAL% 2>&1\n")
            if "sendmail" in line_lower:
                self._write_bloc_relance(f_out, self.phase - 10)
            else:
                f_out.write(f"{self.LIGNE_ERR_1}\n")
            return

        f_out.write(f"{line}\n")

    def generer(self, config: JobConfig) -> bool:
        self.phase = 10 if config.phase_depart == 0 else config.phase_depart
        self.stats = {"phases_generees": 0, "commandes_traitees": 0, "erreurs": 0}

        if not os.path.exists(config.input_path):
            logger.error(f"Fichier introuvable: {config.input_path}")
            console.print(f"[red]❌ Fichier introuvable: {config.input_path}[/red]")
            return False

        try:
            with (
                open(config.input_path, 'r', encoding='utf-8') as f_in,
                open(config.output_path, 'w', encoding='utf-8') as f_out
            ):
                line, eof = self.lire_ligne(f_in)
                if eof:
                    return False
                self.job_name = line
                self.nom_job2 = self.job_name.split('.')[0]

                line, eof = self.lire_ligne(f_in)
                auteur = line if not eof else "UNKNOWN"
                line, eof = self.lire_ligne(f_in)
                lib_job = line if not eof else ""
                line, eof = self.lire_ligne(f_in)
                desc_job = line if not eof else ""

                self._write_entete(f_out, self.nom_job2, config.date_jour,
                                   auteur, lib_job, desc_job, config.username)
                if ".cmd" not in self.job_name:
                    self._write_initialisation(f_out, self.nom_job2)

                while True:
                    line, eof = self.lire_ligne(f_in)
                    if eof:
                        break
                    self._traiter_ligne(f_out, line, f_in)

                self._write_fin_job(f_out)

            self._afficher_stats(config)
            return True

        except UnicodeDecodeError:
            encoding = detect_encoding(config.input_path)
            logger.info(f"Tentative avec encodage {encoding}")
            try:
                return self._generer_avec_encodage(config, encoding)
            except Exception as e2:
                logger.error(f"Échec: {e2}")
                return False
        except Exception as e:
            logger.error(f"Erreur génération: {e}")
            return False

    def _generer_avec_encodage(self, config: JobConfig, encoding: str) -> bool:
        with (
            open(config.input_path, 'r', encoding=encoding) as f_in,
            open(config.output_path, 'w', encoding='utf-8') as f_out
        ):
            line, eof = self.lire_ligne(f_in)
            if eof:
                return False
            self.job_name = line
            self.nom_job2 = self.job_name.split('.')[0]
            line, eof = self.lire_ligne(f_in)
            auteur = line if not eof else "UNKNOWN"
            line, eof = self.lire_ligne(f_in)
            lib_job = line if not eof else ""
            line, eof = self.lire_ligne(f_in)
            desc_job = line if not eof else ""

            self._write_entete(f_out, self.nom_job2, config.date_jour,
                               auteur, lib_job, desc_job, config.username)
            if ".cmd" not in self.job_name:
                self._write_initialisation(f_out, self.nom_job2)
            while True:
                line, eof = self.lire_ligne(f_in)
                if eof:
                    break
                self._traiter_ligne(f_out, line, f_in)
            self._write_fin_job(f_out)

        self._afficher_stats(config)
        return True

    def _afficher_stats(self, config: JobConfig):
        table = Table(
            title=f"✅ Génération: {config.nom_job}",
            box=box.ROUNDED, title_style="bold green"
        )
        table.add_column("Métrique", style="cyan")
        table.add_column("Valeur", style="white", justify="right")
        table.add_row("Phases", str(self.stats["phases_generees"]))
        table.add_row("Commandes", str(self.stats["commandes_traitees"]))
        table.add_row("Erreurs", str(self.stats["erreurs"]))
        table.add_row("Sortie", config.output_path)
        console.print(table)


# ═══════════════════════════════════════════════════════════════
#                   COMPARAISON DE FICHIERS
# ═══════════════════════════════════════════════════════════════

class FileComparator:
    """Comparateur de fichiers avec génération de rapports HTML."""

    @staticmethod
    def compare_to_html(file1_path, file2_path, output_dir, nom_job,
                        encoding1=None, encoding2=None) -> Optional[str]:
        if not os.path.exists(file1_path):
            logger.error(f"Fichier 1 introuvable: {file1_path}")
            return None
        if not os.path.exists(file2_path):
            logger.error(f"Fichier 2 introuvable: {file2_path}")
            return None

        enc1 = encoding1 or detect_encoding(file1_path)
        enc2 = encoding2 or detect_encoding(file2_path)

        try:
            with open(file1_path, 'r', encoding=enc1) as f1:
                lines1 = f1.readlines()
            with open(file2_path, 'r', encoding=enc2) as f2:
                lines2 = f2.readlines()

            html_diff = difflib.HtmlDiff(wrapcolumn=140)
            html_content = html_diff.make_file(
                lines1, lines2,
                fromdesc=f"ANCIEN: {file1_path}",
                todesc=f"NOUVEAU: {file2_path}"
            )

            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            meta = f"""
            <div style="background:#f0f0f0;padding:10px;margin:10px;border-radius:5px;">
                <h3>Rapport de comparaison</h3>
                <p><b>Date:</b> {timestamp} | <b>Utilisateur:</b> {os.getenv('USERNAME', 'N/A')}</p>
                <p><b>Fichier 1:</b> {file1_path} ({enc1})</p>
                <p><b>Fichier 2:</b> {file2_path} ({enc2})</p>
            </div>"""
            html_content = html_content.replace('<body>', f'<body>{meta}')

            output_path = os.path.join(output_dir, f'comparaison_{nom_job}.html')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            return output_path
        except Exception as e:
            logger.error(f"Erreur comparaison: {e}")
            return None

    @staticmethod
    def compare_rapide(file1_path, file2_path) -> Dict:
        try:
            enc1 = detect_encoding(file1_path)
            enc2 = detect_encoding(file2_path)
            with open(file1_path, 'r', encoding=enc1) as f1:
                lines1 = f1.readlines()
            with open(file2_path, 'r', encoding=enc2) as f2:
                lines2 = f2.readlines()

            diff = list(difflib.unified_diff(lines1, lines2))
            ajouts = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
            suppr = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))

            return {
                "identiques": len(diff) == 0,
                "lignes_f1": len(lines1), "lignes_f2": len(lines2),
                "ajouts": ajouts, "suppressions": suppr,
                "total": ajouts + suppr
            }
        except Exception as e:
            return {"erreur": str(e)}


# ═══════════════════════════════════════════════════════════════
#          TRANSFERT DE FICHIERS (AVEC ROUTAGE CORRIGÉ)
# ═══════════════════════════════════════════════════════════════

class FileTransferManager:
    """
    Gestionnaire de transfert avec routage intelligent JOB/SCRIPT/PARAM.

    Le dossier de destination est déterminé automatiquement selon :
        - Le chemin relatif dans Git (prioritaire)
        - L'extension du fichier (.cmd → script, .bat → job)
        - Le type de fichier (_appli, init_var → param)
    """

    def __init__(self, history: HistoryManager, dry_run: bool = False):
        self.history = history
        self.dry_run = dry_run
        self.generator = JobGenerator()
        self.comparator = FileComparator()
        self.results: List[TransferResult] = []

    def transfer_files(
        self, server: str, nom_chaine: str, local_repo_path: str,
        files: List[str], develop_branch: str, transfert: bool
    ) -> List[TransferResult]:
        """Transfère les fichiers avec routage automatique JOB/SCRIPT/PARAM."""
        self.results = []
        FM_path = Path(SCRIPT_PATH, f"{nom_chaine}_{develop_branch}")
        FM_path.mkdir(exist_ok=True)

        date_today = datetime.now().strftime('%d/%m/%Y')
        horodatage = datetime.now().strftime('%Y%m%d')
        username = os.getenv('USERNAME', 'UNKNOWN')

        afficher_resume_operation(
            "Transfert" if transfert else "Génération seule",
            files, server if transfert else "", develop_branch
        )

        for file in files:
            result = self._process_single_file(
                file=file, server=server, nom_chaine=nom_chaine,
                local_repo_path=local_repo_path, FM_path=FM_path,
                date_today=date_today, horodatage=horodatage,
                username=username, transfert=transfert
            )
            self.results.append(result)

        self._afficher_resultats()
        return self.results

    def _process_single_file(
        self, file: str, server: str, nom_chaine: str,
        local_repo_path: str, FM_path: Path, date_today: str,
        horodatage: str, username: str, transfert: bool
    ) -> TransferResult:
        """
        Traite un seul fichier avec routage intelligent.

        Le chemin relatif Git est utilisé pour déterminer le dossier
        de destination sur le serveur.
        """
        file_normalized = file.replace("\\", "/")
        file_windows = file.replace("/", "\\")
        nom_job = os.path.basename(file)

        # ──── ROUTAGE : Déterminer le dossier de destination ────
        dossier_dest = determiner_dossier_serveur(nom_job, file_normalized)
        sous_dossier = extraire_sous_dossier(file_normalized, nom_job)

        console.print(
            f"\n📂 [bold white]{nom_job}[/bold white] → "
            f"Dossier: [bold magenta]{dossier_dest.upper()}[/bold magenta]"
            + (f" / {sous_dossier}" if sous_dossier else "")
        )

        # ──── Déterminer si le fichier doit être généré ────
        needs_generation = (
            (nom_job.lower().endswith('.bat') or nom_job.lower().endswith('.cmd'))
            and 'init_var' not in nom_job.lower()
            and '_appli' not in nom_job.lower()
        )

        path_script = os.path.join(local_repo_path, file_windows)

        if not needs_generation:
            console.print(f"  📋 Copie simple (pas de génération)")
            try:
                shutil.copy(path_script, FM_path)
                self.history.ajouter("copie", {
                    "fichier": nom_job,
                    "dossier_destination": dossier_dest,
                    "resultat": "succès"
                })
                return TransferResult(
                    nom_job, True, "Copié sans génération",
                    dossier_destination=dossier_dest
                )
            except Exception as e:
                return TransferResult(nom_job, False, f"Erreur copie: {e}")
        else:
            console.print(f"  ⚙️  Génération du job...")
            config = JobConfig(
                nom_job=nom_job, input_path=path_script,
                output_path=str(FM_path / nom_job),
                date_jour=date_today, username=username
            )
            success = self.generator.generer(config)
            if not success:
                return TransferResult(nom_job, False, "Échec génération")

            self.history.ajouter("generation", {
                "fichier": nom_job,
                "dossier_destination": dossier_dest,
                "resultat": "succès"
            })

        # ──── TRANSFERT avec chemin correct ────
        if transfert:
            return self._effectuer_transfert(
                nom_job=nom_job,
                server=server,
                nom_chaine=nom_chaine,
                dossier_dest=dossier_dest,
                sous_dossier=sous_dossier,
                FM_path=FM_path,
                horodatage=horodatage
            )

        return TransferResult(
            nom_job, True, "Généré sans transfert",
            dossier_destination=dossier_dest
        )

    def _effectuer_transfert(
        self, nom_job: str, server: str, nom_chaine: str,
        dossier_dest: str, sous_dossier: str,
        FM_path: Path, horodatage: str
    ) -> TransferResult:
        """
        Effectue le transfert réel avec le bon dossier de destination.

        Construit le chemin serveur en utilisant le routage intelligent :
            //serveur/prod/fm/script/fm_kpi.cmd  (pour les .cmd)
            //serveur/prod/fm1/job/jfm1aa/jfm1aa10.bat  (pour les .bat)
        """
        # ──── Construction du chemin avec routage ────
        if sous_dossier:
            file_relative = f"{dossier_dest}/{sous_dossier}/{nom_job}"
        else:
            file_relative = f"{dossier_dest}/{nom_job}"

        source_path = Path(f"//{server}/prod/{nom_chaine}/{file_relative}")
        dest_path = Path(f"//{server}/prod/{nom_chaine}/{file_relative}.{horodatage}")

        console.print(
            f"  🎯 Chemin serveur: [cyan]{source_path}[/cyan]"
        )

        if self.dry_run:
            console.print(
                f"  [yellow]🔍 DRY-RUN: Horodaterait → {dest_path.name}[/yellow]"
            )
            console.print(
                f"  [yellow]🔍 DRY-RUN: Copierait {nom_job} → {source_path}[/yellow]"
            )
            return TransferResult(
                nom_job, True, f"DRY-RUN ({dossier_dest})",
                dossier_destination=dossier_dest,
                chemin_serveur=str(source_path)
            )

        console.print(f"  📤 Transfert vers [bold]{dossier_dest.upper()}[/bold]...")

        # Checksum avant
        checksum_avant = ""
        if source_path.exists():
            checksum_avant = calculer_checksum(str(source_path))

        # Horodatage de l'ancien fichier
        try:
            if source_path.exists():
                console.print(f"  📁 Horodatage: {source_path.name} → {dest_path.name}")
                shutil.move(str(source_path), str(dest_path))
            else:
                console.print(f"  [yellow]⚠ Nouveau fichier (pas d'ancien à horodater)[/yellow]")
        except Exception as e:
            console.print(f"  [red]❌ Erreur horodatage: {e}[/red]")
            return TransferResult(
                nom_job, False, f"Erreur horodatage: {e}",
                dossier_destination=dossier_dest
            )

        # Copie du nouveau fichier
        try:
            shutil.copy(str(FM_path / nom_job), str(source_path))
            console.print(f"  [green]✅ Copié vers {source_path}[/green]")
        except Exception as e:
            console.print(f"  [red]❌ Erreur copie: {e}[/red]")
            self._rollback(dest_path, source_path)
            return TransferResult(
                nom_job, False, f"Erreur copie: {e}",
                dossier_destination=dossier_dest
            )

        # Vérification d'intégrité
        checksum_apres = calculer_checksum(str(source_path))
        checksum_local = calculer_checksum(str(FM_path / nom_job))

        if checksum_apres != checksum_local:
            console.print(f"  [red]❌ Intégrité compromise ![/red]")
            self._rollback(dest_path, source_path)
            return TransferResult(
                nom_job, False, "Intégrité compromise",
                dossier_destination=dossier_dest
            )

        # Comparaison HTML
        if dest_path.exists():
            self.comparator.compare_to_html(
                str(dest_path), str(source_path), str(FM_path), nom_job
            )

        self.history.ajouter("transfert", {
            "fichier": nom_job,
            "serveur": server,
            "dossier_destination": dossier_dest,
            "chemin_complet": str(source_path),
            "checksum_avant": checksum_avant,
            "checksum_apres": checksum_apres,
            "resultat": "succès"
        })

        return TransferResult(
            fichier=nom_job, succes=True,
            message=f"Transféré → {dossier_dest}",
            dossier_destination=dossier_dest,
            chemin_serveur=str(source_path),
            horodatage_ancien=str(dest_path),
            checksum_avant=checksum_avant,
            checksum_apres=checksum_apres
        )

    def _rollback(self, backup_path: Path, target_path: Path):
        console.print("[yellow]🔄 Tentative de rollback...[/yellow]")
        try:
            if backup_path.exists():
                shutil.move(str(backup_path), str(target_path))
                console.print("[green]✅ Rollback réussi[/green]")
            else:
                console.print("[red]❌ Backup introuvable pour rollback[/red]")
        except Exception as e:
            console.print(f"[red]❌ Échec rollback: {e}[/red]")

    def _afficher_resultats(self):
        """Tableau récapitulatif avec la colonne Dossier."""
        table = Table(
            title="Résultats",
            box=box.DOUBLE_EDGE, show_lines=True
        )
        table.add_column("Fichier", style="white", width=25)
        table.add_column("Dossier", style="magenta", width=10)
        table.add_column("Statut", width=10, justify="center")
        table.add_column("Message", style="dim", width=35)

        for r in self.results:
            statut = "[green]✅ OK[/green]" if r.succes else "[red]❌ ÉCHEC[/red]"
            dossier = r.dossier_destination.upper() if r.dossier_destination else "N/A"
            table.add_row(r.fichier, dossier, statut, r.message)

        console.print(table)

        nb_ok = sum(1 for r in self.results if r.succes)
        nb_ko = sum(1 for r in self.results if not r.succes)
        console.print(f"\n📊 Bilan: [green]{nb_ok} succès[/green] / [red]{nb_ko} échec(s)[/red]\n")


# ═══════════════════════════════════════════════════════════════
#                   VALIDATION & BACKUP
# ═══════════════════════════════════════════════════════════════

class JobValidator:
    """Validateur de fichiers batch générés."""

    PATTERNS_OBLIGATOIRES = [
        ('@echo off', "Directive @echo off manquante"),
        ('set PHASE=00', "Phase initiale 00 manquante"),
        ('set PHASE=99', "Phase finale 99 manquante"),
        ('skl_debutjob.pl', "Appel skl_debutjob.pl manquant"),
        ('skl_finjob.pl', "Appel skl_finjob.pl manquant"),
        (':ERREUR', "Label :ERREUR manquant"),
        (':FIN', "Label :FIN manquant"),
    ]

    @classmethod
    def valider(cls, filepath: str) -> Dict:
        resultats = {
            "fichier": filepath, "valide": True,
            "erreurs": [], "avertissements": [], "statistiques": {}
        }
        try:
            encoding = detect_encoding(filepath)
            with open(filepath, 'r', encoding=encoding) as f:
                contenu = f.read()
                lignes = contenu.split('\n')
        except Exception as e:
            resultats["valide"] = False
            resultats["erreurs"].append(f"Lecture impossible: {e}")
            return resultats

        for pattern, message in cls.PATTERNS_OBLIGATOIRES:
            if pattern not in contenu:
                resultats["erreurs"].append(message)
                resultats["valide"] = False

        steps = set(re.findall(r':STEP(\d+)', contenu))
        gotos = re.findall(r'goto STEP(\d+)', contenu)
        for goto in gotos:
            if goto not in steps:
                resultats["avertissements"].append(f"goto STEP{goto} → label inexistant")

        resultats["statistiques"] = {
            "nb_lignes": len(lignes),
            "nb_phases": len(steps),
            "nb_errorlevel": contenu.count('errorlevel'),
        }
        return resultats

    @classmethod
    def afficher_validation(cls, filepath: str):
        r = cls.valider(filepath)
        titre = "[green]✅ VALIDE[/green]" if r["valide"] else "[red]❌ INVALIDE[/red]"
        console.print(Panel(f"Validation: {titre}\nFichier: {r['fichier']}", border_style="cyan"))

        for err in r["erreurs"]:
            console.print(f"  ❌ {err}")
        for warn in r["avertissements"]:
            console.print(f"  ⚠️  {warn}")

        if r["statistiques"]:
            table = Table(box=box.SIMPLE)
            table.add_column("Métrique", style="cyan")
            table.add_column("Valeur", justify="right")
            for k, v in r["statistiques"].items():
                table.add_row(k.replace("nb_", "").title(), str(v))
            console.print(table)


class BackupManager:
    """Gestionnaire de sauvegardes locales."""

    def __init__(self, backup_dir=None):
        self.backup_dir = Path(backup_dir or (SCRIPT_PATH / "backups"))
        self.backup_dir.mkdir(exist_ok=True)

    def creer_backup(self, filepath: str) -> Optional[str]:
        if not os.path.exists(filepath):
            return None
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = self.backup_dir / f"{os.path.basename(filepath)}.{timestamp}.bak"
        try:
            shutil.copy2(filepath, backup_path)
            return str(backup_path)
        except Exception as e:
            logger.error(f"Erreur backup: {e}")
            return None

    def lister_backups(self, filtre: str = "") -> List[Dict]:
        backups = []
        for f in sorted(self.backup_dir.iterdir(), reverse=True):
            if f.is_file() and f.suffix == '.bak':
                if filtre and filtre.lower() not in f.name.lower():
                    continue
                backups.append({
                    "nom": f.name, "chemin": str(f),
                    "taille": f.stat().st_size,
                    "date": datetime.fromtimestamp(f.stat().st_mtime).strftime('%d/%m/%Y %H:%M'),
                })
        return backups

    def restaurer_backup(self, backup_path: str, destination: str) -> bool:
        try:
            shutil.copy2(backup_path, destination)
            return True
        except Exception:
            return False

    def nettoyer(self, jours: int = 30):
        limite = datetime.now().timestamp() - (jours * 86400)
        suppr = sum(1 for f in self.backup_dir.iterdir()
                    if f.is_file() and f.stat().st_mtime < limite and not f.unlink())
        console.print(f"[green]🧹 Backups > {jours} jours nettoyés[/green]")


# ═══════════════════════════════════════════════════════════════
#                   MENU PRINCIPAL
# ═══════════════════════════════════════════════════════════════

def main():
    config_mgr = ConfigManager()
    git_mgr = GitManager(config_mgr)
    history_mgr = HistoryManager()
    backup_mgr = BackupManager()

    console.print(Panel.fit(
        "[bold cyan]🔧 GÉNÉRATEUR DE JOBS AUTOMATISÉ [/bold cyan]\n"
        f"[dim]Utilisateur: {os.getenv('USERNAME', 'N/A')} | "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}[/dim]",
        border_style="bright_blue", box=box.DOUBLE_EDGE
    ))

    while True:
        choix = questionary.select(
            "━━━ MENU PRINCIPAL ━━━",
            choices=[
                questionary.Choice(title="1 - 🤖 Génération automatique (Git)", value="auto"),
                questionary.Choice(title="2 - ✏️  Génération manuelle", value="manuel"),
                questionary.Choice(title="3 - 🔍 Comparer 2 jobs", value="comparaison"),
                questionary.Choice(title="4 - ✅ Valider un job", value="validation"),
                questionary.Choice(title="5 - 📜 Historique", value="historique"),
                questionary.Choice(title="6 - 💾 Sauvegardes", value="sauvegardes"),
                questionary.Choice(title="7 - 🌿 Infos Git", value="git_info"),
                questionary.Choice(title="8 - ⚙️  Paramètres", value="parametres"),
                questionary.Choice(title="9 - 🚪 Quitter", value="quitter"),
            ]
        ).ask()

        if choix is None or choix == "quitter":
            break

        try:
            if choix == "auto":
                _menu_auto(config_mgr, git_mgr, history_mgr)
            elif choix == "manuel":
                _menu_manuel(config_mgr, git_mgr, history_mgr, backup_mgr)
            elif choix == "comparaison":
                _menu_comparaison(config_mgr, git_mgr)
            elif choix == "validation":
                _menu_validation()
            elif choix == "historique":
                _menu_historique(history_mgr)
            elif choix == "sauvegardes":
                _menu_sauvegardes(backup_mgr)
            elif choix == "git_info":
                _menu_git_info(config_mgr, git_mgr)
            elif choix == "parametres":
                _menu_parametres(config_mgr)
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠ Annulé[/yellow]")
        except Exception as e:
            logger.error(f"Erreur: {e}", exc_info=True)
            console.print(f"[red]❌ Erreur: {e}[/red]")

    console.print(Panel.fit(
        "[bold cyan]Merci d'avoir utilisé le Générateur ![/bold cyan]",
        border_style="cyan"
    ))
    questionary.press_any_key_to_continue("Appuyez sur une touche...").ask()


# ═══════════════════════════════════════════════════════════════
#                   SOUS-MENUS
# ═══════════════════════════════════════════════════════════════

def _menu_auto(config_mgr, git_mgr, history_mgr):
    app_config = config_mgr.config

    nom_chaine = questionary.select(
        "Application ?",
        choices=app_config.APPLIS_VALIDES,
        default=config_mgr.config.derniere_application or None
    ).ask()

    config_mgr.config.derniere_application = nom_chaine
    config_mgr.save()

    serveurs = app_config.get_serveurs(nom_chaine)
    serv_label = questionary.select("Serveur ?", choices=list(serveurs.keys())).ask()
    server = serveurs[serv_label]

    path_git = config_mgr.git_path
    if not path_git or not git_mgr.is_valid_git_path(path_git):
        path_git = git_mgr.get_git_path()
        if not path_git:
            return
        config_mgr.git_path = path_git

    local_repo_path = os.path.join(path_git, nom_chaine)
    if not os.path.exists(local_repo_path):
        console.print(f"[red]❌ Chemin inexistant: {local_repo_path}[/red]")
        return

    develop_branch = git_mgr.get_git_branch(local_repo_path)
    if not develop_branch:
        return

    files = git_mgr.get_modified_files(local_repo_path, develop_branch)
    if not files:
        console.print("[yellow]⚠ Aucun fichier modifié.[/yellow]")
        return

    if len(files) > 1:
        selected = questionary.checkbox(
            "Fichiers à traiter:",
            choices=[questionary.Choice(title=f, value=f, checked=True) for f in files]
        ).ask()
        if not selected:
            return
        files = selected

    transfert = questionary.confirm("Effectuer le transfert ?", default=False).ask()

    transfer_mgr = FileTransferManager(history_mgr, dry_run=config_mgr.config.dry_run)
    transfer_mgr.transfer_files(server, nom_chaine, local_repo_path, files, develop_branch, transfert)


def _menu_manuel(config_mgr, git_mgr, history_mgr, backup_mgr):
    nom_job = questionary.text("Nom du job:", validate=validation_nom_job).ask()
    if not nom_job:
        return

    nom_job = nom_job.lower()

    path_git = config_mgr.git_path
    if not path_git or not git_mgr.is_valid_git_path(path_git):
        path_git = git_mgr.get_git_path()
        if not path_git:
            return
        config_mgr.git_path = path_git

    info = extraire_info_job(nom_job)
    fm, sg, folder = info["fm"], info["sg"], info["folder"]

    # ──── Afficher le routage ────
    dossier_dest = determiner_dossier_serveur(nom_job)
    console.print(
        f"📂 Routage: [white]{nom_job}[/white] → "
        f"[bold magenta]{dossier_dest.upper()}[/bold magenta]"
    )

    local_repo_path = os.path.join(path_git, fm)
    if not os.path.exists(local_repo_path):
        console.print(f"[red]❌ Chemin inexistant: {local_repo_path}[/red]")
        return

    develop_branch = git_mgr.get_git_branch(local_repo_path)
    FM_path = Path(SCRIPT_PATH, f"{fm}_{develop_branch}")
    FM_path.mkdir(exist_ok=True)

    input_path = os.path.join(path_git, fm, folder, sg, nom_job)
    output_path = str(FM_path / nom_job)

    if not os.path.exists(input_path):
        console.print(f"[red]❌ Fichier introuvable: {input_path}[/red]")
        alt = questionary.path("Sélectionnez manuellement:").ask()
        if alt and os.path.exists(alt):
            input_path = alt
        else:
            return

    if os.path.exists(output_path):
        backup_mgr.creer_backup(output_path)

    config = JobConfig(
        nom_job=nom_job, input_path=input_path,
        output_path=output_path,
        date_jour=datetime.now().strftime('%d/%m/%Y')
    )

    generator = JobGenerator()
    if generator.generer(config):
        console.print(f"\n[green]✅ {nom_job} généré dans {FM_path}[/green]")
        history_mgr.ajouter("generation_manuelle", {
            "fichier": nom_job,
            "dossier_destination": dossier_dest,
            "resultat": "succès"
        })
        if questionary.confirm("Valider le job ?", default=True).ask():
            JobValidator.afficher_validation(output_path)


def _menu_comparaison(config_mgr, git_mgr):
    mode = questionary.select("Mode:", choices=[
        questionary.Choice(title="Recette vs Prod", value="auto"),
        questionary.Choice(title="Deux fichiers", value="manuel"),
    ]).ask()

    comparator = FileComparator()

    if mode == "auto":
        nom_job = questionary.text("Nom du job:", validate=validation_nom_job).ask()
        if not nom_job:
            return
        nom_job = nom_job.lower()
        info = extraire_info_job(nom_job)
        fm = info["fm"]

        # ──── Routage pour la comparaison aussi ────
        dossier = determiner_dossier_serveur(nom_job)

        FM_path = Path(SCRIPT_PATH, f"{fm}_comparaison")
        FM_path.mkdir(exist_ok=True)

        serveurs = config_mgr.config.get_serveurs(fm)
        server_R = next((v for k, v in serveurs.items() if "recette" in k.lower()), None)
        server_P = next((v for k, v in serveurs.items() if "prod" in k.lower()), None)

        if not server_R or not server_P:
            console.print("[red]❌ Serveurs non configurés[/red]")
            return

        # Utiliser le bon dossier (job ou script)
        file_R = Path(f"//{server_R}/prod/{fm}/{dossier}/{nom_job}")
        file_P = Path(f"//{server_P}/prod/{fm}/{dossier}/{nom_job}")

        console.print(f"📂 Dossier utilisé: [magenta]{dossier.upper()}[/magenta]")
        console.print(f"  Recette: {file_R}")
        console.print(f"  Prod:    {file_P}")

        if not file_R.exists():
            console.print(f"[red]❌ Introuvable: {file_R}[/red]")
            return
        if not file_P.exists():
            console.print(f"[red]❌ Introuvable: {file_P}[/red]")
            return

        stats = comparator.compare_rapide(str(file_P), str(file_R))
        if stats.get("identiques"):
            console.print("[green]✅ Fichiers identiques ![/green]")
            if not questionary.confirm("Générer le HTML ?").ask():
                return

        result = comparator.compare_to_html(str(file_P), str(file_R), str(FM_path), nom_job)
        if result:
            console.print(f"[green]✅ Rapport: {result}[/green]")

    elif mode == "manuel":
        file1 = questionary.path("Fichier 1 (ancien):").ask()
        file2 = questionary.path("Fichier 2 (nouveau):").ask()
        if not file1 or not file2:
            return
        output_dir = str(SCRIPT_PATH)
        nom = Path(file1).stem + "_vs_" + Path(file2).stem
        result = comparator.compare_to_html(file1, file2, output_dir, nom)
        if result:
            console.print(f"[green]✅ Rapport: {result}[/green]")


def _menu_validation():
    filepath = questionary.path("Fichier à valider:").ask()
    if filepath and os.path.exists(filepath):
        JobValidator.afficher_validation(filepath)
    else:
        console.print("[red]❌ Fichier introuvable[/red]")


def _menu_historique(history_mgr):
    action = questionary.select("Action:", choices=[
        questionary.Choice(title="Afficher", value="afficher"),
        questionary.Choice(title="Rechercher", value="rechercher"),
        questionary.Choice(title="Retour", value="retour"),
    ]).ask()

    if action == "afficher":
        nb = questionary.text("Nb entrées:", default="20").ask()
        history_mgr.afficher(int(nb) if nb.isdigit() else 20)
    elif action == "rechercher":
        terme = questionary.text("Recherche:").ask()
        if terme:
            r = history_mgr.chercher(terme)
            if r:
                console.print(f"[green]{len(r)} résultat(s)[/green]")
                for entry in r[-10:]:
                    console.print(f"  • {entry}")
            else:
                console.print("[yellow]Aucun résultat[/yellow]")


def _menu_sauvegardes(backup_mgr):
    action = questionary.select("Action:", choices=[
        questionary.Choice(title="Lister", value="lister"),
        questionary.Choice(title="Restaurer", value="restaurer"),
        questionary.Choice(title="Nettoyer", value="nettoyer"),
        questionary.Choice(title="Retour", value="retour"),
    ]).ask()

    if action == "lister":
        backups = backup_mgr.lister_backups()
        if backups:
            table = Table(title="Sauvegardes", box=box.ROUNDED)
            table.add_column("Nom"); table.add_column("Date"); table.add_column("Taille", justify="right")
            for b in backups[:20]:
                table.add_row(b["nom"], b["date"], f"{b['taille']/1024:.1f} Ko")
            console.print(table)
        else:
            console.print("[yellow]Aucune sauvegarde[/yellow]")
    elif action == "restaurer":
        backups = backup_mgr.lister_backups()
        if not backups:
            console.print("[yellow]Aucune sauvegarde[/yellow]")
            return
        choix = questionary.select("Backup:", choices=[b["nom"] for b in backups[:20]]).ask()
        if choix:
            dest = questionary.path("Destination:").ask()
            path = next(b["chemin"] for b in backups if b["nom"] == choix)
            ok = backup_mgr.restaurer_backup(path, dest)
            console.print("[green]✅ Restauré[/green]" if ok else "[red]❌ Échec[/red]")
    elif action == "nettoyer":
        jours = questionary.text("Supprimer > N jours:", default="30").ask()
        backup_mgr.nettoyer(int(jours) if jours.isdigit() else 30)


def _menu_git_info(config_mgr, git_mgr):
    path_git = config_mgr.git_path
    if not path_git:
        console.print("[yellow]⚠ Aucun dépôt Git configuré[/yellow]")
        return

    app = questionary.select("Application:", choices=config_mgr.config.APPLIS_VALIDES).ask()
    local = os.path.join(path_git, app)
    if not os.path.exists(local):
        console.print(f"[red]❌ Inexistant: {local}[/red]")
        return

    branches = git_mgr.get_all_branches(local)
    current = git_mgr.get_git_branch(local)
    for b in branches:
        console.print(f"  • {b}{' 👈' if b == current else ''}")

    commits = git_mgr.get_commit_info(local, 10)
    if commits:
        table = Table(title="Derniers commits", box=box.SIMPLE)
        table.add_column("Hash", style="yellow", width=10)
        table.add_column("Auteur", style="cyan", width=20)
        table.add_column("Date", width=18)
        table.add_column("Message", style="dim", width=50)
        for c in commits:
            table.add_row(c["hash"], c["auteur"], c["date"], c["message"])
        console.print(table)


def _menu_parametres(config_mgr):
    cfg = config_mgr.config
    table = Table(title="Configuration", box=box.ROUNDED)
    table.add_column("Paramètre", style="cyan")
    table.add_column("Valeur")
    table.add_row("Chemin Git", cfg.git_path or "Non configuré")
    table.add_row("Dernière app", cfg.derniere_application or "N/A")
    table.add_row("Dry-run", "✅" if cfg.dry_run else "❌")
    console.print(table)

    action = questionary.select("Action:", choices=[
        questionary.Choice(title="Modifier chemin Git", value="git"),
        questionary.Choice(
            title=f"{'Désactiver' if cfg.dry_run else 'Activer'} dry-run",
            value="dryrun"
        ),
        questionary.Choice(title="Réinitialiser", value="reset"),
        questionary.Choice(title="Retour", value="retour"),
    ]).ask()

    if action == "git":
        new = GitManager(config_mgr).get_git_path()
        if new:
            config_mgr.git_path = new
    elif action == "dryrun":
        config_mgr.config.dry_run = not cfg.dry_run
        config_mgr.save()
        console.print(f"[green]✅ Dry-run {'activé' if config_mgr.config.dry_run else 'désactivé'}[/green]")
    elif action == "reset":
        if questionary.confirm("Sûr ?", default=False).ask():
            config_mgr.config = AppConfig()
            config_mgr.save()
            console.print("[green]✅ Réinitialisé[/green]")


if __name__ == "__main__":
    main()
