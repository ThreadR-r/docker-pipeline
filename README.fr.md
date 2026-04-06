# Docker-Pipeline 🚀

<p align="center">
  <a href="README.md">English</a> | <a href="README.fr.md">Français</a>
</p>

[![CI/CD](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml)


Docker-Pipeline — un orchestrateur déclaratif léger pour exécuter des étapes Docker.

Un ordonnanceur et exécuteur compacts pour des pipelines YAML : chaque étape exécute un vrai conteneur Docker avec options de politique de pull, retries, délais d'attente et règles de suppression. Des hooks peuvent être ajoutés pour la remédiation ou la notification en cas d'échec.

Marre d'utiliser des orchestrateurs lourds comme Kestra ou Apache Airflow juste pour des pipelines simples ? Docker-Pipeline offre une alternative légère et auditable.

**Pourquoi utiliser Docker-Pipeline** 💡
- **Facile à auditer** : les pipelines sont en YAML — simples à relire et versionner.
- **Comportement réel** : les étapes s'exécutent dans des conteneurs Docker (comme en CI).
- **Contrôle fin** : retries, timeouts, politiques de pull et règles de suppression.
- **Hooks** : `on_retry_step` et `on_failure_step` pour actions automatiques.

**Points forts** ✨
- Modèles validés par Pydantic pour la sécurité et l'auditabilité.
- Runner centré conteneur : chaque étape tourne dans un conteneur isolé.
- Petite API HTTP pour déclenchements ad-hoc et état d'exécution (protégée par clé API).
- Ordonnancement léger via `metadata.schedule`.

## Modes d'utilisation
- **API + Scheduler** (par défaut) : API activée et pipeline fournit `metadata.schedule`.
- **API-only** : API activée, pas de `metadata.schedule`.
- **Scheduler-only** : API désactivée, pipeline ordonnancé via `metadata.schedule`.
- **CLI-only** : pas de schedule et pas d'API → exécutions ponctuelles / validation.

# Démarrage rapide 🧪
## Validation (dry-run)
### Valider le pipeline sans Docker via le package :

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline_simple.yaml --dry-run
```

### Vous pouvez aussi utiliser Docker pour valider le pipeline :

```bash
docker run --rm \
  -v ./example_pipeline_simple.yaml:/pipelines/example_pipeline_simple.yaml:ro \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /pipelines/example_pipeline_simple.yaml --dry-run
```

## Exécuter le pipeline

### Exécuter le conteneur en service avec l'API activée (par défaut) :

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ./pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  -e API_ENABLED=true \
  -e API_KEY=your_api_key_here \
  -e API_PORT=8080 \
  -p 8080:8080 \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml
```

Depuis là, vous pouvez déclencher des exécutions via l'API (ex. `curl -X POST http://localhost:8080/api/v1/trigger -H "X-API-Key: your_api_key_here"`) et consulter l'état (ex. `curl -X GET http://localhost:8080/api/v1/status -H "X-API-Key: your_api_key_here"`) et la santé (ex. `curl -X GET http://localhost:8080/health`).

Si un `schedule` est défini dans le YAML du pipeline (`metadata.schedule`), le pipeline s'exécutera automatiquement selon cette planification.

Remarque : monter le socket Docker donne le contrôle sur le Docker de l'hôte — faites attention.

## Exécutions ponctuelles (`--run-once` / `RUN_ONCE`)

Utilisez `--run-once` pour exécuter le pipeline rendu une seule fois puis quitter. Utile pour des runs ad-hoc ou des jobs CI où vous ne souhaitez pas l'ordonnanceur.

Exemples :

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline pipelines/example_pipeline_simple.yaml --run-once
```

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ./pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml --run-once
```

## Configuration (env & CLI) ⚙️
| Paramètre env | Option CLI | Type | Description |
|---------------|---------------|------|-------------|
| `PIPELINE_FILE` | `--pipeline` | string | Chemin vers le YAML du pipeline (par défaut `/app/pipelines/example_pipeline_simple.yaml`) |
| `PIPELINE_PARAMS` | `--params` | string (JSON) | Paramètres du template du pipeline en JSON (par défaut `{}`) |
| `CRON_SCHEDULE` | `--cron-schedule` | string | Remplace la planification (expression cron) |
| `DOCKER_BASE_URL` | `--docker-url` | string | URL de l'API Docker (par défaut `unix:///var/run/docker.sock`) |
| `API_ENABLED` | `--api-enabled` | boolean | Activer/désactiver l'API (par défaut `true`) |
| `API_HOST` | `--api-host` | string | Hôte de l'API (par défaut `0.0.0.0`) |
| `API_PORT` | `--api-port` | integer | Port de l'API (par défaut `8080`) |
| `API_KEY`, `API_KEYS` | (aucune CLI) | string ou liste séparée par des virgules | Clés d'authentification pour l'API ; le nom d'en-tête est lu depuis `API_KEY_HEADER` (par défaut `X-API-Key`) |
| `API_KEY_HEADER` | (aucune CLI) | string | Nom de l'en-tête utilisé pour la clé API (par défaut `X-API-Key`) |
| `RETRY_ON_FAIL` | `--retry` | integer | Fallback global de retry (par défaut `0`) |
| `STEP_TIMEOUT` | `--step-timeout` | integer | Timeout par défaut des étapes en secondes (par défaut `0`) |
| `RUN_ONCE` | `--run-once` | boolean | Si défini, exécute le pipeline une fois puis quitte |
| `LOG_LEVEL` | `--log-level` | string | Niveau de log (par défaut `INFO`) |

## Schéma du pipeline (résumé) 🗂️
- Niveau supérieur : `metadata` (name, params, schedule, start_pipeline_at_start) et `steps` (liste ordonnée).
- StepModel : `name`, `image`, `cmd`, `env`, `volumes`, `pull_policy`, `retry`, `timeout`, `on_failure`, `on_retry_step`, `on_failure_step`, `remove`, `remove_intermediate`.

## Hooks — résumé 🔁
- `on_retry_step` : s'exécute après une tentative échouée avant la tentative suivante. Variables d'environnement injectées : `RETRY_FOR_STEP`, `LAST_EXIT_CODE`, `RETRY_ATTEMPT`.
- `on_failure_step` : s'exécute après épuisement des retries. Variables d'environnement injectées : `FAILED_STEP`, `FAILED_EXIT_CODE`, `FAILED_ATTEMPT`.

Les hooks ne changent pas la décision du runner (retry ou échec final) ; ils servent à la remédiation/notification.

## Exemple simple

`pipelines/example_pipeline_simple.yaml` :

```yaml
metadata:
  name: simple-pipeline
  params: {}

steps:
  - name: hello
    image: alpine:3.18
    cmd: ["sh","-c","echo Hello world"]
    retry: 0
    timeout: 10
    on_failure: continue
```

## Exemple avancé

```yaml
metadata:
  name: advanced-pipeline
  schedule: "0 * * * *"
  params: {}
  start_pipeline_at_start: true

steps:
  - name: build
    image: alpine:3.18
    cmd: ["sh","-c","echo building; exit 1"]
    retry: 2
    timeout: 30
    pull_policy: if-not-present
    on_retry_step:
      name: cleanup
      image: alpine:3.18
      cmd: ["sh","-c","echo cleanup before retry for ${RETRY_FOR_STEP}"]
    on_failure_step:
      name: notify
      image: alpine:3.18
      cmd: ["sh","-c","echo pipeline failed for ${FAILED_STEP} code=${FAILED_EXIT_CODE}"]
    on_failure: abort
  - name: notify-final
    image: alpine:3.18
    cmd: ["sh","-c","echo pipeline end"]
    retry: 0
```

## Développement & tests 🧰
- Validation dry-run : `uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline_simple.yaml --dry-run`.
- Tests unitaires : ajouter des mocks `pytest` pour le client Docker afin d'assert l'ordre des hooks et l'injection d'env.
- CI : valider tous les YAML dans `pipelines/` et lancer les tests unitaires.

## Contribuer
- Gardez les changements petits et ciblés ; ajoutez des tests pour les changements de comportement.

## Liens utiles
- Documentation pipelines : [docs/pipeline.md](docs/pipeline.md)
- Modèles : [src/pipeline_scheduler/domain/models.py](src/pipeline_scheduler/domain/models.py)
- Runner : [src/pipeline_scheduler/application/runner.py](src/pipeline_scheduler/application/runner.py)
- CLI : [src/pipeline_scheduler/interfaces/cli.py](src/pipeline_scheduler/interfaces/cli.py)

License MIT
