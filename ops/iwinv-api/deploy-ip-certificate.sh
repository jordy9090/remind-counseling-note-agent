#!/bin/sh
set -eu

lineage=/etc/letsencrypt/live/remind-api-ip
[ "${RENEWED_LINEAGE:-}" = "$lineage" ] || exit 0
openssl x509 -in "$lineage/fullchain.pem" -checkip 49.247.174.195 -noout |
    grep -Fqx 'IP 49.247.174.195 does match certificate'
openssl verify -purpose sslserver -CApath /etc/ssl/certs \
    -untrusted "$lineage/chain.pem" "$lineage/cert.pem" >/dev/null

base=/etc/caddy/remind-api-ip
install -d -o root -g caddy -m 0750 "$base"
# Both symlinks belong to the same versioned Certbot lineage. Caddy always
# reads a complete pair, including when the service starts during renewal.
version=$(basename "$(readlink -f "$lineage/cert.pem")" .pem)
dest="$base/$version"
install -d -o root -g caddy -m 0750 "$dest"
install -o root -g caddy -m 0640 "$lineage/privkey.pem" "$dest/privkey.pem"
install -o root -g caddy -m 0640 "$lineage/fullchain.pem" "$dest/fullchain.pem"
ln -sfn "$version" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
if systemctl is-active --quiet remind-api-caddy.service; then
    systemctl reload remind-api-caddy.service
fi
