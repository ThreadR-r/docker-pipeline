
# Docker-Pipeline 🚀

<p align="center">
  <a href="README.md">English</a> | <a href="README.fr.md">Français</a>
</p>

[![CI/CD](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml)


Docker-Pipeline — lightweight declarative orchestrator to run Docker steps.

A compact scheduler and runner for YAML pipelines: each step runs a real Docker container with options for pull policy, retries, timeouts and removal rules. Hooks can be attached for remediation or notification on failures.

Tired of having to use heavy orchestrators like Kestra or Apache Airflow just to run simple pipelines, I created Docker-Pipeline as a lightweight, auditable alternative.

**Why use Docker-Pipeline** 💡
- **Audit-friendly**: pipelines are plain YAML — easy to review and version.
- **Real behavior**: steps run inside Docker containers (same as CI).
- **Fine-grained control**: retries, timeouts, pull policies and removal rules.
- **Hooks**: `on_retry_step` and `on_failure_step` for automatic actions.

**Highlights** ✨
- Pydantic-validated models for safety and auditability.
- Container-first runner: every step runs in an isolated container.
- Small HTTP API for ad-hoc triggers and run status (API-key protected).
- Lightweight cron scheduling via `metadata.schedule`.

## Quick start (dry-run validation) 🧪

### Validate the pipeline without Docker via this repo (fast and safe) :

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run
```

### You can also use Docker to validate the pipeline :

```bash
docker run --rm \
  -v ./example_pipeline.yaml:/pipelines/example_pipeline.yaml:ro \
  docker-pipeline:latest \
  --pipeline /pipelines/example_pipeline.yaml --dry-run
```

## Run in Docker 🐳

Build the image:

```bash
docker build -t docker-pipeline:latest .
```

Run the container:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/pipelines:/app/pipelines:ro \
  -e API_KEY=your_api_key_here \
  docker-pipeline:latest
```

Note: mounting the Docker socket gives control over the host Docker — use with care.

## Usage modes
- **API + Scheduler** (default): API enabled and pipeline provides `metadata.schedule`.
- **API-only**: API enabled, no `metadata.schedule`.
- **Scheduler-only**: API disabled, pipeline scheduled via `metadata.schedule`.
- **CLI-only**: no schedule and no API → one-shot runs / validation.

## Configuration (env & CLI) ⚙️
- `PIPELINE_FILE` / `--pipeline` — path to pipeline YAML (default `/app/pipelines/example_pipeline.yaml`).
- `CRON_SCHEDULE` — override schedule (cron expression).
- `DOCKER_BASE_URL` — Docker API URL (default `unix:///var/run/docker.sock`).
- `API_ENABLED` — `true|false` (default `true`).
- `API_KEY` / `API_KEYS` — API authentication.
- `RETRY_ON_FAIL` / `--retry` — global retry fallback.
- `STEP_TIMEOUT` — default step timeout (seconds).
- `ON_FAILURE` — global behaviour (`abort|continue`).

## Pipeline schema (short) 🗂️
- Top-level: `metadata` (name, params, schedule, start_pipeline_at_start) and `steps` (ordered list).
- StepModel: `name`, `image`, `cmd`, `env`, `volumes`, `pull_policy`, `retry`, `timeout`, `on_failure`, `on_retry_step`, `on_failure_step`, `remove`, `remove_intermediate`.

## Hooks — summary 🔁
- `on_retry_step`: runs after a failed attempt before the next retry. Injected env vars: `RETRY_FOR_STEP`, `LAST_EXIT_CODE`, `RETRY_ATTEMPT`.
- `on_failure_step`: runs after retries are exhausted. Injected env vars: `FAILED_STEP`, `FAILED_EXIT_CODE`, `FAILED_ATTEMPT`.

Hooks do not change the runner's decision (retry or final failure); they are for remediation/notification.

## Simple example

`pipelines/example_pipeline.yaml`:

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

## Advanced example

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

## Development & testing 🧰
- Dry-run validation: `uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run`.
- Unit tests: add `pytest` mocks for the Docker client to assert hooks order and env injection.
- CI recommendation: validate all YAML in `pipelines/` and run unit tests.

## Contributing
- Keep changes small and focused; add tests for behaviour changes.

## Useful links
- Pipeline docs: [docs/pipeline.md](docs/pipeline.md)
- Models: [src/pipeline_scheduler/domain/models.py](src/pipeline_scheduler/domain/models.py)
- Runner: [src/pipeline_scheduler/application/runner.py](src/pipeline_scheduler/application/runner.py)
- CLI: [src/pipeline_scheduler/interfaces/cli.py](src/pipeline_scheduler/interfaces/cli.py)

License MIT
 
# Docker-Pipeline 🚀

Docker-Pipeline — orchestrateur léger déclaratif pour exécuter des étapes Docker.

Un scheduler compact et un runner pour des pipelines YAML : chaque étape lance un conteneur Docker réel avec options pour pull policy, retries, timeouts et règles de suppression. Des hooks peuvent être attachés pour remédiation ou notification en cas d'échecs.

**Pourquoi utiliser Docker-Pipeline** 💡
- **Audit-friendly** : pipelines en YAML, faciles à relire et versionner.
- **Comportement réel** : les étapes tournent dans des conteneurs Docker (comme en CI).
- **Contrôle fin** : retries, timeouts, pull policies et règles de suppression.
- **Hooks** : `on_retry_step` et `on_failure_step` pour actions automatiques.

**Points forts** ✨
- Modèles validés avec Pydantic pour la sécurité et l'auditabilité.
- Runner « container-first » : exécute chaque étape dans un conteneur isolé.
- API HTTP minimale pour déclenchements ad-hoc et état (protégée par clé API).
- Planification cron légère via `metadata.schedule`.

## Démarrage rapide (validation sans Docker) 🧪

Validez un pipeline sans Docker (rapide et sûr) :

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run
```

Cette commande rend et valide le YAML contre les modèles Pydantic sans contacter Docker.

## Exécution en mode conteneur 🐳

Construire l'image :

```bash
docker build -t docker-pipeline:latest .
```

Lancer le conteneur :

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/pipelines:/app/pipelines:ro \
  -e API_KEY=your_api_key_here \
  docker-pipeline:latest
```

Attention : monter le socket Docker donne un contrôle sur le Docker de l'hôte — à utiliser avec précaution.

## Modes d'utilisation
- **API + Scheduler** (par défaut) : API activée et pipeline fournit `metadata.schedule`.
- **API-only** : API activée, pas de `metadata.schedule`.
- **Scheduler-only** : API désactivée, pipeline planifié via `metadata.schedule`.
- **CLI-only** : ni schedule ni API → exécution ponctuelle / validation.

## Configuration (variables d'environnement & CLI) ⚙️
- `PIPELINE_FILE` / `--pipeline` — chemin du YAML (défaut `/app/pipelines/example_pipeline.yaml`).
- `CRON_SCHEDULE` — override de la planification (expression cron).
- `DOCKER_BASE_URL` — URL API Docker (défaut `unix:///var/run/docker.sock`).
- `API_ENABLED` — `true|false` (défaut `true`).
- `API_KEY` / `API_KEYS` — authentification API.
- `RETRY_ON_FAIL` / `--retry` — fallback global de retry.
- `STEP_TIMEOUT` — timeout par défaut des étapes (secondes).
- `ON_FAILURE` — comportement global (`abort|continue`).

## Schéma rapide des pipelines 🗂️
- Top-level : `metadata` (name, params, schedule, start_pipeline_at_start) et `steps` (liste ordonnée).
- StepModel : `name`, `image`, `cmd`, `env`, `volumes`, `pull_policy`, `retry`, `timeout`, `on_failure`, `on_retry_step`, `on_failure_step`, `remove`, `remove_intermediate`.

## Hooks — comportement résumé 🔁
- `on_retry_step` : exécuté après une tentative échouée avant la suivante. Variables injectées : `RETRY_FOR_STEP`, `LAST_EXIT_CODE`, `RETRY_ATTEMPT`.
- `on_failure_step` : exécuté après épuisement des retries. Variables injectées : `FAILED_STEP`, `FAILED_EXIT_CODE`, `FAILED_ATTEMPT`.

Les hooks n'altèrent pas la décision du runner (retry ou failure) ; ils servent à la remédiation/notification.

## Exemple simple

`pipelines/example_pipeline.yaml` :

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
- Validation sans Docker : `uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run`.
- Tests unitaires : ajouter des mocks `pytest` pour le client Docker afin de vérifier l'ordre d'exécution des hooks et l'injection des variables d'environnement.
- CI suggérée : valider tous les YAML `pipelines/` et exécuter les tests.

## Contribuer
- Gardez les changements petits et ciblés ; ajoutez des tests pour toute modification de comportement.

## Liens utiles
- Documentation pipeline : [docs/pipeline.md](docs/pipeline.md)
- Modèles : [src/pipeline_scheduler/domain/models.py](src/pipeline_scheduler/domain/models.py)
- Runner : [src/pipeline_scheduler/application/runner.py](src/pipeline_scheduler/application/runner.py)
- CLI : [src/pipeline_scheduler/interfaces/cli.py](src/pipeline_scheduler/interfaces/cli.py)

License MIT
