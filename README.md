# Cleardeck

Outil d'anonymisation de documents PowerPoint et Word, **100 % local**. Aucun document ne quitte votre poste.

Détection des entités à anonymiser via le modèle CamemBERT-NER (français), combiné aux entités définies par projet. Restauration possible grâce aux fichiers de mapping générés à chaque anonymisation.

---

## Installation (Windows)

1. Téléchargez **`CleardeckSetup.exe`** depuis l'espace SharePoint AI Builders (ou depuis la page [Releases](https://github.com/ArthurCFR/Cleardeck/releases) du dépôt).
2. Double-cliquez sur le fichier.

> **Avertissement Windows Defender SmartScreen**
>
> Le premier lancement affiche un écran bleu : *« Windows a protégé votre PC »*. C'est normal : l'application n'est pas signée par un éditeur reconnu.
>
> 1. Cliquez sur **« Informations complémentaires »**
> 2. Cliquez sur **« Exécuter quand même »**
>
> Windows mémorise votre choix : l'avertissement ne réapparaîtra pas pour les prochains lancements.

3. L'installeur se déroule sans demander de droits administrateur. Il crée :
   - un raccourci dans le menu Démarrer (et sur le Bureau si vous cochez l'option)
   - une entrée dans « Ajouter ou supprimer des programmes »
4. À la fin de l'installation, **Cleardeck se lance automatiquement** dans votre navigateur par défaut.

### Premier lancement

Au tout premier démarrage, l'outil télécharge le modèle d'anonymisation (~400 Mo). Un bandeau jaune en haut de la fenêtre indique la progression. Comptez ~1 à 3 minutes selon votre connexion. Les lancements suivants sont immédiats.

---

## Utilisation rapide

### Anonymiser un document

1. Ouvrez l'onglet **Anonymiser**.
2. Glissez un fichier `.docx` ou `.pptx` dans la grande zone centrale (ou cliquez pour parcourir).
3. Optionnel — associez un **projet** (en haut) pour réutiliser une liste d'entités déjà saisie pour ce client.
4. Cliquez sur **Anonymiser** : l'outil détecte les entités et vous présente un écran de triage.
5. Confirmez/écartez les entités douteuses.
6. Téléchargez le document anonymisé et son fichier `mapping_*.json` (à conserver pour pouvoir restaurer plus tard).

### Anonymiser un lot (jusqu'à 50 documents)

1. Sur l'onglet **Anonymiser**, glissez **plusieurs** documents en une seule fois.
2. Un panneau « Lot de N documents » apparaît.
3. Cliquez **Lancer l'anonymisation du lot**.
   - Toutes les entités détectées sont automatiquement anonymisées (pas de triage individuel).
   - Une barre de progression suit l'avancement.
4. Téléchargez le **ZIP** : il contient les documents anonymisés et un fichier mapping par document.

### Restaurer un document

1. Ouvrez l'onglet **Restaurer**.
2. Glissez le document anonymisé et son fichier `mapping_*.json`.
3. Cliquez sur **Restaurer**.

### Créer un projet (entités client réutilisables)

1. Onglet **Projets** → **Nouveau projet**.
2. Renseignez nom du projet, nom du client, filiales (séparées par des virgules), interlocuteurs.
3. Cliquez **Créer le projet** : l'éditeur s'ouvre avec une liste d'entités pré-amorcée.
4. Ajoutez/modifiez les entités à anonymiser (entreprises, personnes, lieux, autres termes spécifiques).
5. Sauvegardez.

---

## Où sont stockées les données ?

Cleardeck stocke tout localement sur votre poste dans `%LOCALAPPDATA%\Cleardeck\` :

| Dossier | Contenu |
|---|---|
| `models\` | Modèle CamemBERT-NER téléchargé au premier lancement |
| `logs\` | Logs d'exécution (utile en cas de problème) |

Les **projets** sont stockés dans le dossier d'installation de l'application (sous `data\projects\`) et sont conservés lors d'une réinstallation.

---

## Désinstallation

Panneau de configuration Windows → **Ajouter ou supprimer des programmes** → Cleardeck → **Désinstaller**.

---

## Support

- Logs d'exécution : `%LOCALAPPDATA%\Cleardeck\logs\cleardeck.log` (à joindre en cas de bug)
- Issues : https://github.com/ArthurCFR/Cleardeck/issues
