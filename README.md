# Generateur_job_PF
Générateur de job créé et utiliser au sein de l'équipe IT de Pierre Fabre afin de généré des jobs automatiquement et facilement à partir du repo git Pierre Fabre.

**1.Préparation** :

- Copiez l'exécutable sur votre machine locale.
- Assurez-vous que Git est installé et que le dépôt est cloné en local.

**2.Choix de la génération** :

- Vous pouvez opter pour la génération automatique des jobs ou la génération manuelle.

**3.Fonctionnement** :

- Selon votre choix, le programme va identifier la branche Git active en local.
- Il générera les jobs souhaités (en cas de choix manuel) ou les jobs/scripts modifiés entre la branche Git actuelle et la branche master.

**4.Modification et personnalisation** :

- Le fichier generateur.py est disponible pour modifier le code et ajouter des fonctionnalités supplémentaires.
- Cependant, pour utiliser ces modifications, il est nécessaire de générer le fichier .exe. En effet, la génération des fichiers est configurée pour fonctionner avec l'exécutable. Techniquement, le fichier .py fonctionne, mais les fichiers générés seront placés dans un répertoire temporaire AppLocal au lieu d'être créés au même endroit que l'exécutable.

**5. Génération du .exe**

- Avoir python d'installer sur son PC ( et tous les modules nécessaires présents dans le .py ), lancer un cmd où se situe le .py
- Taper : pyinstaller --onefile generateur.py
- Aller chercher le fichier generateur.exe dans le dossier dst
