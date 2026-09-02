# Authent'INT

Sécurisation des accès numériques — DGFiP

## Contexte

**Client :** Direction générale des finances publiques (DGFiP).
Système d'information précédemment compromis.

**Objectif :** sécuriser l'accès à plusieurs services numériques, pour deux
catégories d'utilisateurs : les agents et les contribuables.

## Périmètre

### Dans le périmètre

- Activation de compte et connexion
- Réinitialisation de mot de passe
- Authentification multifacteur (plusieurs facteurs)
- Gestion granulaire de l'accès aux services (via le système de jetons)
- Journalisation des connexions (traçabilité), avec prise en charge de
  plusieurs appareils
- Système d'authentification HTTPS : site accessible en fonction des droits
  des utilisateurs
- SSO : un seul compte par utilisateur, pour toutes les applications
- Page d'accueil listant les différents services

### Hors périmètre

- L'enregistrement des utilisateurs (LDAP) n'est pas à implémenter
- Pas de LDAP à setup : implémenter du LDAP **ou** une base de données pouvant
  se connecter à un LDAP
- Pas de login externe
- Les services externes sont à mocker

## Authentification

- Login : numéro fiscal + mot de passe, pour tous les niveaux d'utilisateurs
- En base : nom + prénom en plus
- Multifacteur : le plus simple == A2F par mail
  (à voir avec le client : serveur mail interne ou fournisseur tiers)
- Base existante avec des utilisateurs déjà créés → activer les comptes
- Traçabilité totale : où l'utilisateur se connecte, qui il est, etc.

## Niveaux d'utilisateurs

Trois niveaux, tous authentifiés de la même façon (numéro fiscal + mot de passe) :

| Niveau | Droits |
| --- | --- |
| Admin | CRUD sur les utilisateurs |
| Agent | Accès à un plus grand nombre de sites fictifs |
| Contribuable | Accès à moins d'applications |

## Outils / mécanismes

- Authentification multifacteur (MFA)
- Système de jetons pour la gestion des accès

## Contraintes

- Pics d'utilisation lors des échéances fiscales (montée en charge /
  scalabilité)
- Forte affluence côté opérateur entre 8h et 10h, et de mai à fin juin :
  20 millions d'utilisateurs simultanés
- Déploiement sur plusieurs sites / centres
- Déploiement dans un cluster Kubernetes, fourni par le client externe
- Architecture résiliente

## Livrables techniques

- Schéma / modèle de base de données
- Points de terminaison des API (endpoints)
- Pages du front-end
- Détail des fonctionnalités dans une partie dédiée du README, puis point
  avec le client pour valider ses besoins réels

## Organisation du projet

- Roadmap pour les prochaines séances
- Créer un dépôt GitHub et le partager
- Nom du groupe : Authent'INT
