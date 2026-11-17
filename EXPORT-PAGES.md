# Export des pages autonomes

L'exporteur construit un dossier indépendant pour chaque page de l'export WordPress, sans modifier les pages originales. Il utilise uniquement Python 3 et les fichiers déjà présents dans le dépôt.

```sh
python3 tools/export_pages.py
```

Le dossier `exports-pages/` et l'archive `pages-hellolead.zip` sont générés à la racine. Ils ne sont pas suivis par Git. Pour éviter d'écraser des fichiers, l'outil refuse de démarrer si l'un de ces chemins existe déjà ; utilisez `--output` et `--zip` pour choisir d'autres noms. Exemple :

```sh
python3 tools/export_pages.py --output mon-export --zip mon-export.zip
```

Chaque page contient `index.html`, `css/`, `js/`, `img/` et `vendor/` (ressources Elementor et autres bibliothèques, dont les chemins restent préservés). Un fichier `RESSOURCES-MANQUANTES.txt` signale les fichiers locaux non trouvés ; l'image `Process-block-1140-×-500-px-1.png` est absente du dépôt pour les deux versions de l'accueil.

Pour consulter une page : placez-vous dans son dossier et lancez `python3 -m http.server 8000` (Windows : `py -m http.server 8000`), puis ouvrez `http://localhost:8000/`. Les liens vers les autres pages du site pointent vers le site public afin de ne pas dépendre des dossiers voisins. Certains services et polices restent externes.

Le reCAPTCHA et les scripts de soumission Contact Form 7 sont retirés dans les **copies exportées**. Les formulaires affichent un avertissement et ne sont pas envoyés ; il faut configurer un service de réception et une protection anti-spam adaptée pour les utiliser en production. Les pages sources et leur configuration WordPress ne sont pas modifiées.

Vérifier l'exporteur : `python3 -m unittest discover -s tests -v`.
