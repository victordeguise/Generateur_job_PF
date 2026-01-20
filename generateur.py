import os
import shutil
import difflib
from datetime import datetime
import subprocess
import sys
import logging
import json

# --- CONFIGURATION DU LOGGING ---
# Le script va écrire dans 'generateur_debug.log' et afficher dans la console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("generateur_debug.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Fichier de config pour mémoriser le chemin Git
CONFIG_FILE = "config_generateur.json"

def get_saved_git_path():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f).get("git_path")
    return None

def save_git_path(path):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"git_path": path}, f)

# --- GESTION DES DEPENDANCES ---
def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        return __import__(import_name)
    except ImportError:
        logging.info(f"Installation du package manquant : {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return __import__(import_name)

git = install_and_import("gitpython", "git")
chardet = install_and_import("chardet")
pathlib = install_and_import("pathlib")
questionary = install_and_import("questionary")
rich = install_and_import("rich")

import rich 
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()
import questionary
import chardet
from pathlib import Path
from git import Repo

# --- CONFIGURATION DU CHEMIN RACINE (Compatible .EXE) ---
if getattr(sys, 'frozen', False):
    script_path = Path(sys.executable).parent.absolute()
else:
    script_path = Path(__file__).parent.absolute()
    
def afficher_cadre(titre, lignes):
    largeur = max(len(ligne) for ligne in lignes + [titre]) + 4
    print("+" + "-" * largeur + "+")
    print("| " + titre.center(largeur - 2) + " |")
    print("+" + "-" * largeur + "+")
    for ligne in lignes:
        print("| " + ligne.ljust(largeur - 2) + " |")
    print("+" + "-" * largeur + "+")

# ===================== Fonctions Git =====================

def is_valid_git_path(path):
    """Vérifie si le chemin contient un dépôt Git valide."""
    try:
        repo = Repo(path)
        # Si l'initialisation du Repo réussit, le chemin est valide
        return True
    except Exception:
        # Si une exception est levée, le chemin n'est pas un dépôt Git valide
        logging.info("Chemin du dépôt Git introuvable ou invalide.")
        return False

def get_git_path():
    print("Recherche du chemin Git...")
    home_dir = os.path.expanduser("~")
    for root, dirs, _ in os.walk(home_dir):
        if '.git' in dirs:
            git_path = os.path.abspath(root)
            print(f"Chemin Git trouvé: {git_path}")
            
            # Demander à l'utilisateur de valider le chemin
            user_validation = input("Voulez-vous utiliser ce chemin ? (o/n) ").lower()
            if user_validation == 'o':
                return git_path
            else:
                print("Continuer la recherche...")
    
    # Si aucun chemin n'a été validé, demander à l'utilisateur d'entrer un chemin
    while True:
        git_path = input("Aucun chemin Git valide trouvé. Veuillez entrer manuellement le chemin du dépôt Git: ")
        if is_valid_git_path(git_path):
            print("Chemin Git valide.")
            return git_path

def get_git_branch(local_repo_path):
    repo = Repo(local_repo_path)
    branch_name = repo.active_branch.name
    console.print(f"Branche git active: [bold green]{branch_name}[/bold green]")
    return branch_name

def get_modified_files(local_repo_path, develop_branch):
    repo = Repo(local_repo_path)
    modified_files = repo.git.diff('master', develop_branch, name_only=True).split('\n')
    console.print(f"Fichiers modifiés: [bold white]{modified_files}[/bold white]")
    return modified_files

# ===================== Fonctions de génération de job =====================

def lire_fice1(file):
    """Fonction pour lire le fichier d'entrée ligne par ligne"""
    while True :
        line = file.readline()
        if not line:
            return None, True  # Fin de fichier
        line = line.strip()
        if line:  # Si la ligne n'est pas vide
            return line, False

def generateur_job(fic1_in,fic1_out,date_jour,phase_depart,username):
    # Ouverture du fichier d'entrée
    try:
        with open(fic1_in, 'r', encoding='utf-8') as f_in:
            pass  # Just to check if it exists
    except FileNotFoundError:
        logging.info(f"Impossibilité d'ouvrir le fichier en entrée : <{fic1_in}> !")

    # Ouverture du fichier de sortie en écriture
    try:
        with open(fic1_out, 'w', encoding='utf-8') as f_out:
            pass  # Just to check if it can be created
    except IOError:
        logging.info(f"Impossibilité de créer le fichier en sortie : <{fic1_out}> !")

    # Initialisation variable
    phase = 10
    
    # Initialisation des lignes standards
    ligne_rem_1 = "rem ######################################################################"
    ligne_rem_2 = "rem #---------------------------------------------------------------------"
    ligne_rem_3 = "rem #--              "
    ligne_rem_4 = "rem ##################################################"
    ligne_set_1 = "set NOMTRAIT="
    ligne_inf_1 = "%PERL% %PF_SKL_PROC%\\skl_infojob.pl \"%PHASE%\" \"%NOMTRAIT%\""
    ligne_err_1 = "if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & goto ERREUR\n"
    ligne_err_2 = "if %errorlevel% GTR 1 set ERR=Erreur execution %NOMTRAIT% & goto ERREUR"
    send_mail = "call %PF_SCRIPT%\\sendMail.cmd %num_phase% %nom_job%"
    ligne_copy_1 = "rem --------------------------------------------------"
    ligne_copy_2 = "rem Parametres de"

    # Définir la phase si départ n'est pas 0
    if phase_depart != 0:
        phase = phase_depart

    # Ouverture du fichier d'entrée et traitement
    with open(fic1_in, 'r', encoding='utf-8') as f_in, open(fic1_out, 'w', encoding='utf-8') as f_out:
        # Lecture du nom du fichier
        line, end_of_file = lire_fice1(f_in)
        if not end_of_file:
            job_name = line
            nom_job2 = job_name.split('.')[0]
        
        # Lecture des informations
        line, end_of_file = lire_fice1(f_in)
        auteur = line
        line, end_of_file = lire_fice1(f_in)
        lib_job = line
        line, end_of_file = lire_fice1(f_in)
        desc_job = line

        # Écriture de l'en-tête dans le fichier de sortie
        f_out.write('@echo off\n')
        f_out.write(f"{ligne_rem_1}\n")
        f_out.write(f"{ligne_rem_2}\n")
        f_out.write(f"rem #-- Nom     : {nom_job2}\n")
        f_out.write(f"rem #-- Version : 1.00                   Date : {date_jour}\n")
        f_out.write(f"rem #-- Auteur  : {auteur}\n")
        f_out.write(f"{ligne_rem_2}\n")
        f_out.write(f"rem #-- Objet   : {lib_job}\n")
        f_out.write(f"rem #--           {desc_job}\n")
        f_out.write(f"{ligne_rem_2}\n")
        f_out.write(f"rem #-- Commentaires :\n")
        f_out.write(f"{ligne_rem_3}\n")
        f_out.write(f"{ligne_rem_2}\n")
        f_out.write(f"rem #--               Auteur   |      Date\n")
        f_out.write(f"{ligne_rem_2}\n")
        f_out.write(f"{ligne_rem_3} {username}  |    {date_jour}\n")
        f_out.write(f"{ligne_rem_2}\n")
        f_out.write(f"{ligne_rem_1}\n\n")

        # Si le job est de type ".cmd", ne pas écrire les lignes en sortie
        if ".cmd" not in job_name:
            f_out.write("rem Chargement du .profile\n")
            f_out.write("call %0\\..\\..\\..\\skl\\param\\profile.bat\n\n")
            f_out.write("rem Récup des paramètres\n")
            f_out.write("set SCHEDULE_NAME_PLAN=%1\n\n\n")
            f_out.write("rem Chargement de l'environnement\n")
            f_out.write("%PF_PERLENV%perl %0\\..\\..\\..\\skl\\param\\skl_uni_env.pl %0 > %0_env.bat\n")
            f_out.write("call %0_env.bat\n")
            f_out.write("del  %0_env.bat\n\n")
            f_out.write("rem Chargement de l'env spécif\n")
            f_out.write("if exist %PF_PARAM%\\%PF_APPLI%_appli.bat call %PF_PARAM%\\%PF_APPLI%_appli.bat\n\n")
            f_out.write(f"set nom_job={nom_job2}\n\n")
            f_out.write(f"{ligne_rem_4}\n")
            f_out.write("set PHASE=00 - Début du job\n")
            f_out.write(f"{ligne_rem_4}\n")
            f_out.write("%PERL% %PF_SKL_PROC%\\skl_debutjob.pl\n\n")
            f_out.write("%D% && cd %FM_PROG%\n")
            f_out.write("rem goto STEP000\n")
        # Traitement du fichier d'entrée ligne par ligne (commentées et autres commandes)
        while True:
            line, end_of_file = lire_fice1(f_in)
            if end_of_file:
                break
                
            if line.lower().startswith("rem"):
                # Si c'est une ligne commentée, gérer la logique en fonction
                if line[4] == '-' and line.count('-') >= 2:
                    # Vérifier si l'une des sous-chaînes est présente dans la ligne
                    if any(substring in line for substring in ['sort', 'ls', 'wc', 'keybuild', 'dbcheck', 'dchain', 'export', 'pexport', 'mail', 'cat', 'uniq', 'grep', 'join', 'sed', 'gawk', '7zip']):
                        f_out.write("set nberr=0\n")
                    f_out.write(f":STEP{phase}\n")
                    f_out.write(f"{ligne_rem_4}\n")
                    title = line.split('-')
                    lib_phase = title[2]
                    f_out.write(f"set PHASE={job_name} - {phase} - {lib_phase}\n")
                    f_out.write(f"{ligne_rem_4}\n")
                    f_out.write(f"set num_phase={phase}\n")
                    trt = title[1]
                    f_out.write(f"{ligne_set_1}{trt}\n")
                    f_out.write(f"{ligne_inf_1}\n\n")
                    phase += 10
                    
                    
            # La ligne lue est une commande FM
            elif "%FM_PROG%" in line:
                if any(cmd in line for cmd in ["dbcheck","dchain","keybuild","pexport"]):
                    PHASE_prec = phase - 10
                    # pas de redirection de la sortie standard des pexports
                    if "pexport" in line:
                        f_out.write(f"{line}\n")
                    else:
                        f_out.write(f"{line} >> %JOURNAL% 2>&1 \n")
                    
                    f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                    f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                    f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                    f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                    f_out.write(f":finSTEP{PHASE_prec}\n\n")
                    
                    PHASE_prec_1 = PHASE_prec
                    
                # La ligne lue est un pimport
                elif "pimport" in line:
                    PHASE_prec = phase - 10
                    f_out.write(f"{line}\n")
                    if ',' not in line:
                        f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                        f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                        f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                        f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                        f_out.write(f":finSTEP{PHASE_prec}\n\n")
                    else:
                        f_out.write(f"{ligne_err_1}\n")
                
                else:  # exception pour les tests d'équilibrage
                    f_out.write(f"{line}\n")
                    if line[25:29] in ["5100", "5101", "5102"]:
                        f_out.write(f"{ligne_err_2}\n")
                    else:
                        f_out.write(f"{ligne_err_1}\n")
                    
            elif "%PF_EXE" in line:
                PHASE_prec = phase - 10
                # Paramètre de relance automatique de chaîne
                if "join" in line:
                    f_out.write(f"{line} 2>> %JOURNAL%\n")
                    f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                    f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                    f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                    f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                    f_out.write(f":finSTEP{PHASE_prec}\n\n")
                    
                elif "grep" in line:
                    f_out.write(f"{line} 2>> %JOURNAL%\n")
                    f_out.write(f"if %errorlevel% LSS 2 goto finSTEP{PHASE_prec}\n")
                    f_out.write(f"if %errorlevel% GTR 1 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                    f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                    f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                    f_out.write(f":finSTEP{PHASE_prec}\n\n")
                    
                elif any(cmd in line for cmd in ["fmfileconverter","fmfilesort"]):
                    f_out.write(f"{line} 2>> %JOURNAL%\n")
                    f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                    f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                    f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                    f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                    f_out.write(f":finSTEP{PHASE_prec}\n\n")
                    
                elif "cat" in line:
                    f_out.write(f"{line} 2>> %JOURNAL%\n")
                    f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                    f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                    f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                    f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                    f_out.write(f":finSTEP{PHASE_prec}\n\n")

                # uniq : mettre une ligne d'erreur et relance automatique pour chaque ligne
                elif "uniq" in line:
                    f_out.write(f"{line} 2>> %JOURNAL%\n")

                    # Mettre une phase intermédiaire entre les deux lignes de uniq
                    next_line, end_of_file = lire_fice1(f_in)
                    if "uniq" in next_line:
                        # Phase intermédiaire
                        PHASE_p = phase - 5
                        
                        f_out.write(f"if %errorlevel% EQU 0 goto STEP{PHASE_p}\n")
                        f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                        f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                        f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                        f_out.write(f":STEP{PHASE_p}\n{next_line} 2>> %JOURNAL%\n")
                        f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                        f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                        f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_p}\n")
                        f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                        f_out.write(f":finSTEP{PHASE_prec}\n\n")
                    else:
                        f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                        f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                        f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                        f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                        f_out.write(f":finSTEP{PHASE_prec}\n\n")
                        # line = next_line

                else:
                    f_out.write(f"{line} 2>> %JOURNAL%\n")
                    if "unix2dos" in line or "touch" in line:
                        f_out.write(f"{ligne_err_1}")
                    else:
                        f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                        f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                        f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                        f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                        f_out.write(f":finSTEP{PHASE_prec}\n\n")
                        
            elif "forfiles" in line:
                f_out.write(f"{line} >> %JOURNAL% 2>&1\n\n")
            # Gestion des boucles FOR
            elif "for" in line:
                f_out.write(f"{line}\n")
                count1 = line.count('(')
                count2 = line.count(')')
                if count1 != count2:
                    line, end_of_file = lire_fice1(f_in)
                    while line != ")":
                        if not (line[:3].lower() == "rem"):
                            f_out.write(f"{line} 2>> %JOURNAL%\n")
                            f_out.write(f"{ligne_err_2}\n")
                        else:
                            f_out.write(f"{line}\n")
                        line, end_of_file = lire_fice1(f_in)
                    f_out.write(f"{line}\n")

            # Gestion des IF
            elif any(cmd in line for cmd in ["if",":","goto","set","type","mkdir","rmdir","echo","find","ping","dir"]):
                f_out.write(f"{line}\n")

            # Gestion des CALL
            elif "call" in line or "Program Files" in line:
                f_out.write(f"{line}\n")
                f_out.write(f"{ligne_err_1}\n")

            # Gestion des mouvements de fichiers MOVE/COPY/DEL
            elif "move" in line or "copy" in line:
                mvt_type = line[:4]
                f_out.write(f"{ligne_copy_1}\n{ligne_copy_2} {mvt_type}\n")
                f_out.write(f"echo Source :  {line.split()[1]} >> %JOURNAL% 2>&1\necho Cible :   {line.split()[2]} >> %JOURNAL% 2>&1\n")
                f_out.write(f"{ligne_copy_1}\n\n")
                f_out.write(f"{line} >> %JOURNAL% 2>&1\n\n")

            elif "del" in line:
                f_out.write(f"{line} >> %JOURNAL% 2>&1\n")

            elif "%PERL%" in line:
                f_out.write(f"{line} >> %JOURNAL% 2>&1\n")
                if "sendmail" in line:
                    PHASE_prec = phase - 10
                    f_out.write(f"if %errorlevel% EQU 0 goto finSTEP{PHASE_prec}\n")
                    f_out.write(f"if %errorlevel% NEQ 0 set ERR=Erreur execution %NOMTRAIT% & set /a nberr = %nberr%+1\n")
                    f_out.write(f"if %nberr% EQU 1 {send_mail} & goto STEP{PHASE_prec}\n")
                    f_out.write("if %nberr% GTR 1 goto ERREUR\n")
                    f_out.write(f":finSTEP{PHASE_prec}\n\n")
                else:
                    f_out.write(f"{ligne_err_1}\n")

            else:
                if line[:3].lower() != "rem":
                    f_out.write(f"{line}\n")
                    
        # Gestion de la fin du job
        f_out.write("\n")
        f_out.write(f"{ligne_rem_4}\n")
        f_out.write("set PHASE=99 - Fin du job\n")
        f_out.write(f"{ligne_rem_4}\n")
        f_out.write(f"%PERL% %PF_SKL_PROC%\\skl_finjob.pl\n\n")
        f_out.write("goto FIN\n\n\n")
        f_out.write(f"{ligne_rem_4}\n")
        f_out.write("rem GESTION DES ERREURS\n")
        f_out.write(f"{ligne_rem_4}\n\n")
        f_out.write(":ERREUR\n")
        f_out.write(f"%PERL% %PF_SKL_PROC%\\skl_message.pl F %ERRORLEVEL% %ERR%\n")
        f_out.write(f"copy /y %fmdata%*.%numVERSION% %D%\\prod\\%nomCHAINE%\\save\\erreur\\ >> %JOURNAL% 2>&1\n")
        f_out.write(f"%EXIT% 8\n")
        f_out.write("exit   8\n\n")
        f_out.write(":FIN\n")
        f_out.write(f"%EXIT% 0\n\n");
        

# ===================== Fonction pour la comparaison =====================

def detect_encoding(file_path):
    """ Fonction pour détecter l'encodage d'un fichier """
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        return result['encoding']
        
def compare_files_to_html(file1_path, file2_path, encoding1, encoding2, nom_job, FM_path):
    """ Fonction pour créer un report de comparaison HTML entre le job généré et l'ancien job """
    # Lire les fichiers avec les encodages spécifiés
    with open(file1_path, 'r', encoding=encoding1) as file1, open(file2_path, 'r', encoding=encoding2) as file2:
        file1_lines = file1.readlines()
        file2_lines = file2.readlines()

    html_diff = difflib.HtmlDiff(wrapcolumn=140)
    html_content = html_diff.make_file(file1_lines, file2_lines, fromdesc=file1_path, todesc=file2_path)

    with open(os.path.join(FM_path, f'comparaison_{nom_job}.html'), 'w', encoding='utf-8') as html_file:
        return html_file.write(html_content)
    
# ===================== Fonction de transfert sur le serveur =====================

def transfer_files(server, nom_chaine, local_repo_path, files, develop_branch, transfert):
    """ Fonction pour transférer les fichiers sur le serveur et older l'ancien """
    console.print("[bold purple]#####################################[/bold purple]")
    FM_path = Path(script_path, f"{nom_chaine}_{develop_branch}")
    FM_path.mkdir(exist_ok=True)
    date_today = datetime.now().strftime('%d/%m/%Y')
    year = datetime.now().strftime('%Y')
    month = datetime.now().strftime('%m')
    day = datetime.now().strftime('%d')
    for file in files:
        file = file.replace("/", "\\")
        nom_job = os.path.basename(file)
        path_script = os.path.join(local_repo_path, file)
        
        # Vérifier l'extension du fichier
        if not (file.endswith('.bat') or file.endswith('.cmd')) or 'init_var' in file or '_appli' in file:
            console.print(f"Le fichier [bold white]{nom_job}[/bold white] n'a pas besoin d'être généré.")
            shutil.copy(path_script, FM_path)
        else:
            console.print(f"Génération du job: [bold white]{nom_job}[/bold white]")
            file = f"job\\{nom_job}"
            generateur_job(path_script, os.path.join(FM_path, nom_job), date_today, 0, os.getenv('USERNAME'))

        if transfert :
            console.print(f"Transfert de [bold white]{nom_job}[/bold white]...")
            source_path = Path(f"//{server}/prod/{nom_chaine}/{file}")
            dest_path = Path(f"//{server}/prod/{nom_chaine}/{file}.{year}{month}{day}")
            print(f"Horodatage de {source_path} en {dest_path}")
            try:
                shutil.move(source_path, dest_path)
                print("Fichier déplacé avec succès.")
            except Exception as e:
                console.print(f"[bold red]❌ ERREUR :[/bold red] {str(e)}")
            print(f"Copie de {os.path.join(FM_path, nom_job)} vers {source_path}")
            try:
                shutil.copy(os.path.join(FM_path, nom_job), source_path)
                print("Fichier déplacé avec succès.")
            except Exception as e:
                console.print(f"[bold red]❌ ERREUR :[/bold red] {str(e)}")
            console.print("[bold purple]########### Fin du transfert ##################[/bold purple]")
            
            encoding1 = detect_encoding(dest_path)
            encoding2 = detect_encoding(source_path)

            compare_files_to_html(dest_path, source_path, encoding1, encoding2, nom_job, FM_path)
            console.print(f"[bold purple]########### Comparaison HTML généré dans {FM_path} ##################[/bold purple]")
    if not transfert:
        console.print("[bold purple]########### Fin de la génération des fichiers sans transfert ##################[/bold purple]")

def validation_job(text):
    # 1. Vérification de l'extension
    if not text.lower().endswith(('.bat', '.cmd')):
        return "Le job doit finir par .bat ou .cmd"
    
    # 2. Vérification des caractères interdits (Windows)
    if any(char in text for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
        return "Le nom contient des caractères interdits"
    
    return True
 
# ===================== Menu =====================

def main():
    console.print(Panel.fit(
        "[bold cyan]GÉNÉRATEUR DE JOBS AUTOMATISÉ[/bold cyan]\n[italic white]Optimisation & Déploiement FM[/italic white]",
        border_style="bright_blue",
        box=box.DOUBLE_EDGE
    ))
    
    applis_valides = ["fm1", "fm2", "fm3", "fm4", "fm5", "fm6", "fm7", "fm8", "fm9", "fm", "fm0"]

    while True:
        # menu interactif
        choix = questionary.select(
            "--- MENU PRINCIPAL ---",
            choices=[
                questionary.Choice(title="1 - Générer le job automatiquement (auto)", value="auto"),
                questionary.Choice(title="2 - Générer le job manuellement (manuel)", value="manuel"),
                questionary.Choice(title="3 - Comparer 2 jobs (recette vs prod)", value="comparaison"),
                questionary.Choice(title="4 - Quitter", value="quitter")
            ]
        ).ask()
        if choix == "quitter":
            break
            
        if choix == "auto":
            # Choix de l'application
            nom_chaine = questionary.select(
                "Quelle est l'application ?",
                choices=applis_valides,
                ).ask()

            # Choix du serveur
            if nom_chaine == "fm4":
                serveurs = {"recette fm4": "pfadc6fm4app01r", "prod fm4": "pfadc2fm4app01p"}
            else:
                serveurs = {"recette": "pfovhvrfmxapp01", "prod": "pfovhvpfmxapp01"}
            
            serv_label = questionary.select("Sur quel serveur déployer ?", choices=list(serveurs.keys())).ask()
            server = serveurs[serv_label]

            # Gestion du chemin Git
            path_git = get_saved_git_path()
            if not path_git or not is_valid_git_path(path_git):
                path_git = get_git_path()
                if path_git:
                    save_git_path(path_git)

            local_repo_path = os.path.join(path_git, nom_chaine)
            develop_branch = get_git_branch(local_repo_path)
            files = get_modified_files(local_repo_path, develop_branch)

            if not files or files == ['']:
                console.print("[bold yellow]⚠ Aucun fichier modifié n'a été trouvé dans le dépôt.[/bold yellow]")
                continue

            # Confirmation du transfert
            transfert = questionary.confirm("Voulez-vous effectuer le transfert des fichiers ?").ask()
            
            transfer_files(server, nom_chaine, local_repo_path, files, develop_branch, transfert)
            break

        elif choix == "manuel":
            nom_job = questionary.text("Nom du job .bat (ex: jfm1aa10.bat) :", validate=validation_job).ask().lower()
            path_git = get_saved_git_path()
            if not path_git or not is_valid_git_path(path_git):
                path_git = get_git_path()
                if path_git:
                    save_git_path(path_git)
            date_today = datetime.now().strftime('%d/%m/%Y')
            username = os.getenv('USERNAME')
            FM = nom_job[1:4]
            SG = nom_job[0:6]
            local_repo_path = os.path.join(path_git, FM)
            develop_branch = get_git_branch(local_repo_path)
            FM_path = Path(script_path, f"{FM}_{develop_branch}")
            FM_path.mkdir(exist_ok=True)
            generateur_job(os.path.join(path_git, FM, "JOB", SG, nom_job), os.path.join(FM_path, nom_job), date_today, 0, username)
            console.print(f"Fichier [bold green]{nom_job}[/bold green] généré")

        elif choix == "comparaison":
            nom_job = questionary.text("Nom du job .bat (ex: jfm1aa10.bat) :", validate=validation_job).ask().lower()
            FM = nom_job[1:4]
            FM_path = Path(script_path, f"{FM}_comparaison")
            FM_path.mkdir(exist_ok=True)
            server_R7 = "pfadc6fm4app01r" if FM.upper() == "FM4" else "pfovhvrfmxapp01"
            serveur_prod = "pfadc2fm4app01p" if FM.upper() == "FM4" else "pfovhvpfmxapp01"
            source_path = Path(f"//{server_R7}/prod/{FM}/job/{nom_job}")
            dest_path = Path(f"//{serveur_prod}/prod/{FM}/job/{nom_job}")
            encoding1 = detect_encoding(dest_path)
            encoding2 = detect_encoding(source_path)
            compare_files_to_html(dest_path, source_path, encoding1, encoding2, nom_job, FM_path)
            console.print("[green]Fichier de comparaison généré[/green]")
            
    console.print(Panel.fit(
    "[bold cyan]Merci d'avoir utilisé le Générateur de Jobs ![/bold cyan]\n",
    border_style="cyan"
    ))
    questionary.press_any_key_to_continue("Appuyez sur une touche pour quitter...").ask()
            
if __name__ == "__main__":
    main()