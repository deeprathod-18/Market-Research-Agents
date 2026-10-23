Deployment files live in the project root so each platform can find them:

- `Dockerfile`, `docker-compose.yml`, `.dockerignore`: container build (Hugging Face Spaces, Render, any Docker host)
- `render.yaml`: Render blueprint
- `.streamlit/config.toml`: Streamlit server and theme settings
- `.github/workflows/ci.yml`: automated tests on every push

Step-by-step instructions: see `DEPLOYMENT_STEPS.md`.
