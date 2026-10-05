import {
  bucket,
  defineRailway,
  github,
  postgres,
  preserve,
  project,
  ref,
  service,
  volume,
} from "railway/iac";

export default defineRailway(() => {
  const Postgres = postgres("Postgres", { region: "iad" });
  const postgresVolume = volume("postgres-volume", {
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
    allowOnlineResize: true,
    region: "iad",
    sizeMB: 500,
  });
  const reports = bucket("reports", { region: "iad" });
  const source = github("AnarchI-Technologies-MAIN/stewardence-mvp-v1.8", {
    branch: "main",
  });
  const commonRuntime = {
    DJANGO_SETTINGS_MODULE: "agentledger.settings.production",
    DJANGO_SECRET_KEY: preserve(),
    ALLOWED_HOSTS: preserve(),
    CSRF_TRUSTED_ORIGINS: preserve(),
    APP_BASE_URL: preserve(),
    REPORTS_BUCKET_NAME: ref(reports, "BUCKET"),
    REPORTS_BUCKET_ENDPOINT: ref(reports, "ENDPOINT"),
    REPORTS_BUCKET_ACCESS_KEY_ID: ref(reports, "ACCESS_KEY_ID"),
    REPORTS_BUCKET_SECRET_ACCESS_KEY: ref(reports, "SECRET_ACCESS_KEY"),
    REPORTS_BUCKET_REGION: ref(reports, "REGION"),
    REPORTS_BUCKET_URL_STYLE: "virtual",
    RENDERER_PRIVATE_URL: "http://renderer.railway.internal:8080",
    REPORT_RENDERER_URL: "http://renderer.railway.internal:8080",
  };

  const web = service("web", {
    source,
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "uv run --no-sync gunicorn --config src/agentledger/gunicorn.conf.py agentledger.wsgi:application",
    healthcheck: "/readyz",
    healthcheckTimeout: 300,
    deploy: { restartPolicyType: "ALWAYS", sleepApplication: false },
    replicas: { iad: 1 },
    env: {
      ...commonRuntime,
      DATABASE_URL: preserve(),
    },
  });

  const worker = service("worker", {
    source,
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "uv run --no-sync python manage.py run_worker",
    deploy: { restartPolicyType: "ALWAYS", sleepApplication: false },
    replicas: { iad: 1 },
    env: {
      ...commonRuntime,
      DATABASE_URL: preserve(),
    },
  });

  const renderer = service("renderer", {
    source,
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile.renderer" },
    healthcheck: "/healthz",
    healthcheckTimeout: 300,
    deploy: { restartPolicyType: "ALWAYS", sleepApplication: false },
    replicas: { iad: 1 },
  });

  return project("stewardence-production", {
    resources: [Postgres, postgresVolume, reports, web, worker, renderer],
  });
});
