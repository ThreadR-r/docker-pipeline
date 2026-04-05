 
<p align="center">
  <a href="README.md">English</a> | <a href="README.fr.md">Français</a>
</p>

# Docker-Pipeline 🚀

Docker-Pipeline — orchestrateur léger déclaratif pour exécuter des étapes Docker.

Un scheduler compact et un runner pour des pipelines YAML : chaque étape lance un conteneur Docker réel avec options pour pull policy, retries, timeouts et règles de suppression. Des hooks peuvent être attachés pour remédiation ou notification en cas d'échecs.

Fatigué d'utiliser des orchestrateurs lourds comme Kestra ou Apache Airflow juste pour exécuter des pipelines simples, j'ai créé Docker-Pipeline comme une alternative légère et auditée.

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

## Démarrage rapide 🧪

### Validez un pipeline sans Docker en utilisant ce dépôt (rapide et sûr) :

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run
```

Cette commande rend et valide le YAML contre les modèles Pydantic sans contacter Docker.

### Vous pouvez aussi utiliser docker pour valider un pipeline :

```bash
docker run --rm \
  -v ./example_pipeline.yaml:/pipelines/example_pipeline.yaml:ro \
  docker-pipeline:latest \
  --pipeline /pipelines/example_pipeline.yaml --dry-run
```

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
