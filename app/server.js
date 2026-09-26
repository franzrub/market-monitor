const http = require('http'), fs = require('fs'), path = require('path');
const port = process.env.PORT || 8080;
const file = path.join(__dirname, 'index.html');
http.createServer((req, res) => {
  if (req.url === '/healthz') { res.writeHead(200); return res.end('ok'); }
  fs.readFile(file, (e, b) => {
    if (e) { res.writeHead(500, {'content-type':'text/plain'}); return res.end('build missing'); }
    res.writeHead(200, {'content-type':'text/html; charset=utf-8','cache-control':'no-store'});
    res.end(b);
  });
}).listen(port, () => console.log('listening on', port));
