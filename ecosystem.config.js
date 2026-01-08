module.exports = {
  apps: [
    {
      name: "zeta-sync-cluster",
      script: "main.py",
      interpreter: "python3",
      cwd: __dirname,
      autorestart: true,
      watch: false,
    }
  ]
};
