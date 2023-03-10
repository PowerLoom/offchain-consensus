// this means if app restart {MAX_RESTART} times in 1 min then it stops

const { readFileSync } = require('fs');
const settings = JSON.parse(readFileSync('settings/settings.json'));

const NODE_ENV = process.env.NODE_ENV || 'development';

const MAX_RESTART = 10;
const MIN_UPTIME = 60000;


module.exports = {
  apps : [
    {
      name   : "epoch-generator",
      script : `poetry run python -m epoch_generator`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "off-chain-consensus",
      script: `poetry run gunicorn -k uvicorn.workers.UvicornWorker consensus_entry_point:app --workers 20 -b ${settings.consensus_service.host}:${settings.consensus_service.port}`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    }
  ]
}
