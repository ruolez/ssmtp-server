// Report each accepted message to the Flask internal event API at queue time.
// Keyed by the transaction uuid, which the outbound system reuses as
// hmail.todo.uuid — that's how outbound_logger correlates delivery results.

const http = require('http');
const https = require('https');
const urllib = require('url');

function postEvent(plugin, payload) {
  // Haraka's plugin sandbox does not expose the global URL constructor,
  // so parse with the legacy url.parse instead.
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

// Convert a Haraka address object to a string. Across address-rfc2821 versions
// `.address` is sometimes a method and sometimes a plain string property, so
// handle both rather than assuming one shape.
function addrToString(addr) {
  if (!addr) return null;
  if (typeof addr.address === 'function') return addr.address();
  if (typeof addr.address === 'string') return addr.address;
  return typeof addr.toString === 'function' ? addr.toString() : String(addr);
}

function logQueued(plugin, connection) {
  const txn = connection.transaction;
  if (!txn) return;
  try {
    const subject = txn.header.get('Subject');
    const messageId = txn.header.get('Message-ID');
    postEvent(plugin, {
      type: 'queued',
      uuid: txn.uuid,
      app_id: connection.notes.app_id || null,
      mail_from: addrToString(txn.mail_from),
      rcpt_to: (txn.rcpt_to || []).map(addrToString).filter(Boolean).join(', '),
      subject: subject ? subject.trim() : null,
      message_id: messageId ? messageId.trim() : null,
      size: txn.data_bytes || null,
    });
  } catch (e) {
    // Never let a logging error disrupt mail flow.
    plugin.logerror('event_logger logQueued error: ' + e.message);
  }
}

// Relaying (authenticated) mail fires queue_outbound; keep hook_queue too for
// completeness. Returning CONT lets Haraka's core hand the message to outbound.
exports.hook_queue_outbound = function (next, connection) {
  logQueued(this, connection);
  return next();
};

exports.hook_queue = function (next, connection) {
  logQueued(this, connection);
  return next();
};
