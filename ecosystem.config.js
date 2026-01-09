module.exports = {
  apps: [
    {
      name: "zeta-sync",
      cwd: __dirname,
      script: "./.venv/bin/python",
      args: "-m uvicorn main:app --host 0.0.0.0 --port 8080",
      env: {
        APP_ENV: "prod"
      },
      autorestart: true,
      watch: false
    }
  ]
};
