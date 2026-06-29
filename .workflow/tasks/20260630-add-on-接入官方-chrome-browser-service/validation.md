# Validation: Add-on 接入官方 Chrome browser-service

## Acceptance checklist
- [x] Core behavior lands on the real entry path.
- [x] Validation commands cover the nearest risk.
- [x] Diff scope matches the task.
- [x] Handoff is current.

## Commands run
| Command | Result | Evidence |
|---|---:|---|
| `git diff --check` | PASS | no whitespace errors |
| `bash -n scripts/docker-entrypoint.sh scripts/browser-service-entrypoint.sh` | PASS | shell syntax OK |
| `python3 -m py_compile scripts/browser.py scripts/browser_service.py` | PASS | Python syntax OK |
| YAML load for `config.yaml`, `.github/workflows/docker-image.yml`, `docker-compose.yml`, `repository.yaml` | PASS | `yaml ok` |
| `PYTHONPATH=scripts python3 -m unittest scripts.test_mqtt_publisher -v` | PASS | 3 tests OK |
| `PYTHONPATH=scripts python3 -m unittest discover -s tests -v` | PASS | 49 tests OK |
| `docker build -f Dockerfile-for-github-action -t sgcc-app-addon-test .` | PASS | app/Add-on image rebuilt after final entrypoint changes |
| `docker build -f Dockerfile.browser -t sgcc-browser-test .` | PASS | sidecar browser image built |
| `cp example.env .env && docker compose config >/tmp/sgcc-compose-config.yml` | PASS | app/browser image names rendered; default `browser-service`; Compose explicitly sets `SGCC_BROWSER_SERVICE_EMBEDDED=false` and `SGCC_LOAD_ADDON_OPTIONS=false` |
| Add-on embedded smoke | PASS | entrypoint read `/data/options.json`, started embedded browser-service; dummy main saw `mode=browser-service`, `cdp=127.0.0.1:19224`, `service=http://127.0.0.1:39224`, health `ready=False running=False` before Chrome launch |
| Sidecar smoke | PASS | isolated ports `39223/19223`; `/start` launched official Chrome; CDP `/json/version` reported `Chrome/149.0.7827.200`; `/stop` left `ready=false`, `running=false` |
| app→sidecar Selenium/CDP attach smoke | PASS | isolated ports `39225/19225`; `build_driver()` attached to official Chrome; userAgent returned `Chrome/149...`; `release_driver()` stopped Chrome |

## Manual smoke
- Add-on smoke used simulated `/data/options.json` and temporary dummy `/app/main.py` inside built image to prove single-container embedded manager startup without touching real SGCC credentials.
- Sidecar/app smoke used local test images on isolated ports only and stopped Chrome after validation.

## Anti-slop checklist
- [x] No placeholder on core path.
- [x] No mock-only delivery; dummy main was smoke-only.
- [x] New files are referenced by real workflow or documented as task artifacts.
- [x] Risks and rollback are written.

## Release readiness
- Target: `main` + tag `v0.1.4`.
- Build: app and browser images build locally; CI configured to publish both to GHCR/ACR.
- Config: Add-on defaults to `browser-service`; fallback `local` retained.
- External publication: GitHub push/tag triggers image publishing; no secrets added.
- Rollback: `SGCC_BROWSER_MODE=local`, previous image tag, or revert commit.

## Remaining risk
- RK001 is an upstream SGCC/Tencent risk signal; this release improves the browser runtime but cannot guarantee every account/IP/context avoids RK001.
- Add-on currently declares `amd64` only because official Chrome package and validated image path are amd64.


## v0.1.4 patch validation
- `v0.1.3` CI succeeded, but anonymous pull check showed ACR app was public while new `sgcc_ha_browser` repository returned `insufficient_scope`.
- v0.1.4 changes ACR browser publishing to the existing public `sgcc_ha` repository with `browser-*` tags.
- Validation rerun: `git diff --check`, shell syntax, Python compile, YAML parse, 3+49 unit tests, `docker compose config`.
