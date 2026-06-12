// Report outbound delivery outcomes (delivered / deferred / bounced) to the
// Flask internal event API, correlated by hmail.todo.uuid.

const http = require('http');
const https = require('https');
const urllib = require('url');

function postEvent(plugin, payload) {
  // Haraka's plugin sandbox does not expose the global URL constructor.
  const target = urllib.parse(
    (process.env.WEB_INTERNAL_URL || 'http://web:8000') + '/internal/events'
  );
  const body = JSON.stringify(payload);
  const lib = target.protocol === 'https:' ? https : http;
  const req = lib.request(
    {
      hostname: target.hostname,
      port: target.port || (target.protocol === 'https:' ? 443 : 80),
      path: target.path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'X-Internal-Secret': process.env.INTERNAL_SECRET || '',
      },
    },
    (res) => res.resume()
  );
  req.on('error', (e) => plugin.logerror('event post failed: ' + e.message));
  req.write(body);
  req.end();
}

function uuidOf(hmail) {
  // Outbound appends ".<index>" to the transaction uuid (outbound/index.js).
  // Strip that trailing segment to recover the submission uuid we logged.
  if (!hmail || !hmail.todo || !hmail.todo.uuid) return null;
  return hmail.todo.uuid.replace(/\.\d+$/, '');
}

// params: [host, ip, response, delay, port, mode, ok_recips, secured]
exports.hook_delivered = function (next, hmail, params) {
  postEvent(this, {
    type: 'delivered',
    uuid: uuidOf(hmail),
    remote_mx: params && params[0] ? params[0] : null,
    smtp_response: params && params[2] ? String(params[2]) : null,
    attempt_no: hmail && hmail.num_failures ? hmail.num_failures + 1 : 1,
  });
  return next();
};

// params: { delay, err }
exports.hook_deferred = function (next, hmail, params) {
  postEvent(this, {
    type: 'deferred',
    uuid: uuidOf(hmail),
    smtp_response: params && params.err ? String(params.err) : null,
    attempt_no: hmail && hmail.num_failures ? hmail.num_failures : 1,
  });
  // CONT so Haraka reschedules the retry.
  return next();
};

exports.hook_bounce = function (next, hmail, error) {
  postEvent(this, {
    type: 'bounce',
    uuid: uuidOf(hmail),
    smtp_response: error ? String(error) : null,
    attempt_no: hmail && hmail.num_failures ? hmail.num_failures : 1,
  });
  // CONT so Haraka still emits the standard bounce message to the sender.
  return next();
};
