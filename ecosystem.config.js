module.exports = {
  apps: [
    {
      name: "zeta-sync",
      cwd: __dirname,
      interpreter: "./.venv/bin/python",
      script: "main.py",
      autorestart: true,
      watch: false
    }
  ]
};
