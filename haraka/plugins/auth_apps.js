// Authenticate SMTP submission against the `apps` table in Postgres.
// On success Haraka's auth_base sets connection.relaying = true, which is the
// ONLY way a recipient is accepted — so this is what keeps us from being an
// open relay.

const { Pool } = require('pg');
const bcrypt = require('bcryptjs');

let pool;

exports.register = function () {
  this.inherits('auth/auth_base');
  pool = new Pool({
    host: process.env.POSTGRES_HOST || 'db',
    port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
    user: process.env.POSTGRES_USER || 'ssmtp',
    password: process.env.POSTGRES_PASSWORD || '',
    database: process.env.POSTGRES_DB || 'ssmtp',
    max: 4,
  });
  pool.on('error', (err) => this.logerror('pg pool error: ' + err.message));
};

exports.hook_capabilities = function (next, connection) {
  // Only offer AUTH over TLS so credentials are never sent in the clear.
  if (connection.tls.enabled) {
    const methods = ['PLAIN', 'LOGIN'];
    connection.capabilities.push('AUTH ' + methods.join(' '));
    connection.notes.allowed_auth_methods = methods;
  }
  next();
};

exports.check_plain_passwd = function (connection, user, passwd, cb) {
  pool
    .query(
      'SELECT id, smtp_password_hash, enabled FROM apps WHERE smtp_username = $1',
      [user]
    )
    .then((res) => {
      if (res.rows.length === 0) return cb(false);
      const row = res.rows[0];
      if (!row.enabled) {
        connection.loginfo(this, `auth rejected: app "${user}" is disabled`);
        return cb(false);
      }
      const ok = bcrypt.compareSync(passwd, row.smtp_password_hash);
      if (ok) {
        connection.notes.app_id = row.id;
        connection.notes.app_user = user;
      }
      return cb(ok);
    })
    .catch((err) => {
      connection.logerror(this, 'auth_apps db error: ' + err.message);
      return cb(false);
    });
};

// Accept recipients only for authenticated (relaying) connections.
exports.hook_rcpt = function (next, connection) {
  if (connection.relaying) return next(OK);
  return next(DENY, 'Relaying denied — authenticate first');
};
