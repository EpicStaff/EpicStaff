#!/bin/bash
set -e

# >>> env_bool
# Strict boolean environment flag, accepting exactly the values Env.bool accepts
# (src/shared/envtools.py). Copied verbatim into every script that needs it;
# .github/scripts/check_env_conventions.py fails CI if the copies or the values drift.
# Usage: if env_bool NAME [DEFAULT]; then ...; fi
# Returns 0 for true and 1 for false. DEFAULT applies only when NAME is unset.
# An unset NAME without DEFAULT, or any other value, exits the script with 64.
env_bool() {
  eval "env_bool_is_set=\${$1+set}"
  if [ -n "$env_bool_is_set" ]; then
    eval "env_bool_value=\${$1}"
  elif [ $# -ge 2 ]; then
    env_bool_value=$2
  else
    echo "ERROR: environment variable $1 is not set." >&2
    exit 64
  fi
  case "$(printf '%s' "$env_bool_value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')" in
    1|on|t|true|y|yes) return 0 ;;
    0|f|false|n|no|off) return 1 ;;
  esac
  echo "ERROR: environment variable $1='$env_bool_value' is not a boolean. Use one of 1, on, t, true, y, yes for true or 0, f, false, n, no, off for false (case-insensitive)." >&2
  exit 64
}
# <<< env_bool

if ! env_bool SESSION_AUDIT_TRAIL_ENABLED && ! env_bool USER_AUDIT_TRAIL_ENABLED; then
    echo "SESSION_AUDIT_TRAIL_ENABLED and USER_AUDIT_TRAIL_ENABLED are both false - opensearch has nothing to do, exiting."
    exit 0
fi

OPENSEARCH_HOME=/usr/share/opensearch
OPENSEARCH_CONFIG_DIR="$OPENSEARCH_HOME/config"
SECURITY_TOOLS_DIR="$OPENSEARCH_HOME/plugins/opensearch-security/tools"
# The image's default security configuration (config.yml, roles.yml, roles_mapping.yml, ...), with
# internal_users.yml replaced by write_internal_users. The demo installer changes nothing here but
# the admin password hash.
SECURITY_CONFIG_DIR="$OPENSEARCH_CONFIG_DIR/opensearch-security"
INTERNAL_USERS_FILE="$SECURITY_CONFIG_DIR/internal_users.yml"
# The compose healthcheck reports healthy only once this exists, so a failed sync shows as unhealthy.
# It lives in the container filesystem, which a restart keeps: remove it before every sync.
INTERNAL_USERS_SYNCED_MARKER=/tmp/internal-users-synced
SECURITY_CONFIG_SYNC_LOG=/tmp/security-config-sync.log
# Written once the whole security configuration has been pushed over whatever the security index held,
# i.e. once it is known to hold the image's defaults and no user but admin, and SSL dual mode has been
# cleared from the cluster settings (see clear_ssl_dual_mode). Until then OpenSearch
# listens on loopback only: a data volume the demo configuration set up may hold the demo users, and
# anything that whoever held the public demo admin certificate (kirk.pem) wrote into it, such as
# anonymous access or a role mapping that grants it every index. It lives on the opensearch_data
# volume, next to the security index it vouches for, so a replaced or restored data volume brings its
# own state (or none) with it.
SECURITY_CONFIG_RESET_FLAG="$OPENSEARCH_HOME/data/.epicstaff-security-config-reset"
# A sync that keeps failing is retried for as long as the node runs and reported this often, so the
# first report is in the log well before the healthcheck turns unhealthy (start_period 300 s + 30
# retries x 10 s).
SECURITY_CONFIG_SYNC_REPORT_INTERVAL_SECONDS=240

# The node's PKI, generated on every start into a tmpfs that compose mounts owned by opensearch: the
# keys never reach a disk or a volume and are gone once the container stops. The security plugin only
# reads files under the config directory, hence the mount point.
TLS_DIR="$OPENSEARCH_CONFIG_DIR/tls"
TLS_CA_CERT="$TLS_DIR/root-ca.pem"
TLS_NODE_CERT="$TLS_DIR/node.pem"
TLS_NODE_KEY="$TLS_DIR/node-key.pem"
TLS_ADMIN_CERT="$TLS_DIR/admin.pem"
TLS_ADMIN_KEY="$TLS_DIR/admin-key.pem"
TLS_CA_DN="CN=EpicStaff OpenSearch Root CA,O=EpicStaff"
TLS_NODE_DN="CN=opensearch,OU=node,O=EpicStaff"
TLS_ADMIN_DN="CN=opensearch-admin,OU=admin,O=EpicStaff"
# Must outlast any container's uptime: nothing renews the certificates before the next start.
TLS_VALIDITY_DAYS=3650

# The security plugin's demo installer rejected a weak admin password on every new container. This
# keeps its regex rule; it also required a zxcvbn score, which has no shell equivalent.
check_admin_password_strength() {
    local password=$OPENSEARCH_INITIAL_ADMIN_PASSWORD
    if (( ${#password} < 8 )) || [[ ! $password =~ [[:upper:]] || ! $password =~ [[:lower:]] \
            || ! $password =~ [[:digit:]] || ! $password =~ [^[:alnum:]] ]]; then
        echo "ERROR: OPENSEARCH_PASSWORD needs at least 8 characters, with upper case, lower case, digit and special characters." >&2
        exit 1
    fi
}

# Issues a key pair for DN, signed by the CA in WORK_DIR/ca.p12, as the PEM files the security plugin
# and securityadmin read: the certificate to CERT_FILE, the unencrypted PKCS#8 key to KEY_FILE.
# Usage: issue_certificate WORK_DIR ALIAS DN EXTENDED_KEY_USAGE CERT_FILE KEY_FILE [SUBJECT_ALT_NAMES]
issue_certificate() {
    local work_dir=$1 alias=$2 dn=$3 extended_key_usage=$4 cert_file=$5 key_file=$6 subject_alt_names=${7:-}
    local keystore="$work_dir/$alias.p12"
    local extensions=(-ext "ku:c=digitalSignature,keyEncipherment" -ext "eku=$extended_key_usage")
    if [[ -n "$subject_alt_names" ]]; then
        extensions+=(-ext "san=$subject_alt_names")
    fi
    # The validity only keeps keytool's log line from announcing its 90-day default: the throwaway
    # self-signed certificate it applies to is replaced by the one -gencert issues.
    keytool -genkeypair -alias "$alias" -dname "$dn" -keyalg RSA -keysize 3072 \
        -validity "$TLS_VALIDITY_DAYS" \
        -keystore "$keystore" -storetype PKCS12 -storepass:env TLS_STORE_PASSWORD
    keytool -certreq -alias "$alias" -file "$work_dir/$alias.csr" \
        -keystore "$keystore" -storepass:env TLS_STORE_PASSWORD
    keytool -gencert -alias ca -infile "$work_dir/$alias.csr" -outfile "$work_dir/$alias.pem" -rfc \
        -validity "$TLS_VALIDITY_DAYS" "${extensions[@]}" \
        -keystore "$work_dir/ca.p12" -storepass:env TLS_STORE_PASSWORD
    java "$work_dir/ExportPrivateKey.java" "$keystore" "$alias" "$work_dir/$alias-key.pem"
    chmod 600 "$work_dir/$alias-key.pem"
    mv "$work_dir/$alias-key.pem" "$key_file"
    mv "$work_dir/$alias.pem" "$cert_file"
}

# Replaces the security plugin's demo PKI, which ships in every OpenSearch image and in the plugin's
# public repository: whoever holds its kirk.pem admin certificate is a superuser without a password.
# A new set on every start, so nothing renews or rotates it; no client pins the CA. The CA key only
# signs the node and admin certificates and is then discarded, so it cannot be stolen to mint another
# admin certificate.
generate_tls_certificates() {
    # In the tmpfs too, so no private key ever lands in the container filesystem.
    local work_dir="$TLS_DIR/generating"
    echo "Generating this start's TLS certificates in $TLS_DIR."
    mkdir -m 700 "$work_dir"
    # Protects the throwaway PKCS#12 stores; keytool reads it from the environment, not the command line.
    TLS_STORE_PASSWORD=$(head -c 32 /dev/urandom | base64)
    export TLS_STORE_PASSWORD
    # keytool cannot write a private key as PEM, which the security plugin and securityadmin need.
    cat > "$work_dir/ExportPrivateKey.java" <<'JAVA'
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.util.Base64;

public class ExportPrivateKey {
    public static void main(String[] args) throws Exception {
        char[] password = System.getenv("TLS_STORE_PASSWORD").toCharArray();
        KeyStore keystore = KeyStore.getInstance("PKCS12");
        try (var input = Files.newInputStream(Path.of(args[0]))) {
            keystore.load(input, password);
        }
        byte[] pkcs8 = keystore.getKey(args[1], password).getEncoded();
        // The PEM label is kept apart from the dashes so the secret scanner does not read this
        // template as a committed private key.
        String label = "PRIVATE KEY";
        String pem = "-----BEGIN " + label + "-----\n"
            + Base64.getMimeEncoder(64, "\n".getBytes(StandardCharsets.US_ASCII)).encodeToString(pkcs8)
            + "\n-----END " + label + "-----\n";
        Files.writeString(Path.of(args[2]), pem, StandardCharsets.US_ASCII);
    }
}
JAVA

    keytool -genkeypair -alias ca -dname "$TLS_CA_DN" -keyalg RSA -keysize 4096 \
        -validity "$TLS_VALIDITY_DAYS" -ext "bc:c=ca:true,pathlen:0" -ext "ku:c=keyCertSign,cRLSign" \
        -keystore "$work_dir/ca.p12" -storetype PKCS12 -storepass:env TLS_STORE_PASSWORD
    keytool -exportcert -alias ca -rfc -file "$work_dir/root-ca.pem" \
        -keystore "$work_dir/ca.p12" -storepass:env TLS_STORE_PASSWORD
    # The node certificate serves HTTPS and the node-to-node transport, so it needs both usages. The
    # names cover the healthcheck and securityadmin (localhost) and the auditor (the service name).
    issue_certificate "$work_dir" node "$TLS_NODE_DN" serverAuth,clientAuth \
        "$TLS_NODE_CERT" "$TLS_NODE_KEY" "dns:localhost,ip:127.0.0.1,dns:opensearch"
    issue_certificate "$work_dir" admin "$TLS_ADMIN_DN" clientAuth "$TLS_ADMIN_CERT" "$TLS_ADMIN_KEY"
    mv "$work_dir/root-ca.pem" "$TLS_CA_CERT"
    rm -rf "$work_dir"
    unset TLS_STORE_PASSWORD
}

# The node's whole configuration. It lives in the container filesystem, so a new container starts
# from the image's file; writing it on every start also moves a node first set up with the demo
# configuration onto this start's PKI. Only certificates signed by this start's CA are trusted,
# only the admin DN may change the security index, and with allow_unsafe_democertificates
# left unset the plugin refuses to start if it is ever handed the demo certificates. The remaining
# plugins.security settings are the ones the demo installer wrote, so nothing else changes.
# NETWORK_HOST binds both the REST API and the transport: 0.0.0.0 because Docker picks the address,
# or _local_ (loopback only, which a single-node cluster allows) until the security index is reset.
# Usage: write_opensearch_config NETWORK_HOST
write_opensearch_config() {
    local network_host=$1
    cat > "$OPENSEARCH_CONFIG_DIR/opensearch.yml" <<EOF
cluster.name: docker-cluster
network.host: $network_host

plugins.security.ssl.transport.pemcert_filepath: tls/node.pem
plugins.security.ssl.transport.pemkey_filepath: tls/node-key.pem
plugins.security.ssl.transport.pemtrustedcas_filepath: tls/root-ca.pem
plugins.security.ssl.transport.enforce_hostname_verification: false
plugins.security.ssl.http.enabled: true
plugins.security.ssl.http.pemcert_filepath: tls/node.pem
plugins.security.ssl.http.pemkey_filepath: tls/node-key.pem
plugins.security.ssl.http.pemtrustedcas_filepath: tls/root-ca.pem
plugins.security.allow_default_init_securityindex: true
plugins.security.authcz.admin_dn: ['$TLS_ADMIN_DN']
plugins.security.nodes_dn: ['$TLS_NODE_DN']
plugins.security.audit.type: internal_opensearch
plugins.security.enable_snapshot_restore_privilege: true
plugins.security.check_snapshot_restore_write_privileges: true
plugins.security.restapi.roles_enabled: [all_access, security_rest_api_access]
plugins.security.system_indices.enabled: true
plugins.security.system_indices.indices: [.plugins-ml-agent, .plugins-ml-config, .plugins-ml-connector,
  .plugins-ml-controller, .plugins-ml-model-group, .plugins-ml-model, .plugins-ml-task,
  .plugins-ml-conversation-meta, .plugins-ml-conversation-interactions, .plugins-ml-memory-meta,
  .plugins-ml-memory-message, .plugins-ml-stop-words, .opendistro-alerting-config,
  .opendistro-alerting-alert*, .opendistro-anomaly-results*, .opendistro-anomaly-detector*,
  .opendistro-anomaly-checkpoints, .opendistro-anomaly-detection-state, .opendistro-reports-*,
  .opensearch-notifications-*, .opensearch-notebooks, .opensearch-observability, .ql-datasources,
  .opendistro-asynchronous-search-response*, .replication-metadata-store, .opensearch-knn-models,
  .geospatial-ip2geo-data*, .plugins-flow-framework-config, .plugins-flow-framework-templates,
  .plugins-flow-framework-state]
node.max_local_storage_nodes: 3
EOF
}

# Writes the only internal user EpicStaff needs: admin, with the password from the environment.
# The demo configuration also ships anomalyadmin, kibanaserver, kibanaro, logstash, readall and
# snapshotrestore, each with its user name as password; readall, kibanaro and anomalyadmin can
# read every index, the audit trail included.
write_internal_users() {
    local admin_hash
    admin_hash=$(bash "$SECURITY_TOOLS_DIR/hash.sh" -env OPENSEARCH_INITIAL_ADMIN_PASSWORD | tail -n 1)
    if [[ "$admin_hash" != "\$2y\$"* ]]; then
        echo "ERROR: hashing OPENSEARCH_INITIAL_ADMIN_PASSWORD failed: $admin_hash" >&2
        exit 1
    fi
    cat > "$INTERNAL_USERS_FILE" <<EOF
_meta:
  type: "internalusers"
  config_version: 2

admin:
  hash: "$admin_hash"
  reserved: true
  backend_roles:
  - "admin"
  description: "EpicStaff admin user, used by the auditor"
EOF
}

# SSL dual mode makes the transport port (9300) accept plaintext next to TLS. It is a dynamic cluster
# setting, so it lives in the cluster state, not the security index: a holder of the demo admin
# certificate could have turned it on persistently, the security index reset leaves it in place, and
# it overrides opensearch.yml. The security plugin reads plugins.security_config.ssl_dual_mode_enabled
# and, while that is unset, falls back to the legacy opendistro_security_config.ssl_dual_mode_enabled,
# so either key turns dual mode on. Removes both, persistent and transient, in one request
# with the admin certificate; the node applies that at once. Idempotent; nothing EpicStaff runs needs dual mode.
# Prints the response.
clear_ssl_dual_mode() {
    local response
    response=$(curl -sS --max-time 30 --cacert "$TLS_CA_CERT" --cert "$TLS_ADMIN_CERT" --key "$TLS_ADMIN_KEY" \
        -X PUT -H 'Content-Type: application/json' https://localhost:9200/_cluster/settings \
        -d '{"persistent":{"plugins.security_config.ssl_dual_mode_enabled":null,"opendistro_security_config.ssl_dual_mode_enabled":null},"transient":{"plugins.security_config.ssl_dual_mode_enabled":null,"opendistro_security_config.ssl_dual_mode_enabled":null}}') \
        || return 1
    echo "SSL dual mode cluster setting clear: $response"
    [[ "$response" == *'"acknowledged":true'* ]]
}

# The node reads the security configuration files only when it creates the security index, so on a
# data volume initialised by an earlier start whatever the index holds survives. securityadmin pushes
# the files over it, then clear_ssl_dual_mode runs: the sync has succeeded only once both have.
# SCOPE picks what securityadmin pushes:
#   all             every file in SECURITY_CONFIG_DIR: resets the whole index to the image's defaults
#                   plus our internal users. Run until the reset flag exists, i.e. once per data volume.
#   internal_users  internal_users.yml only: run on every later start, so a changed OPENSEARCH_PASSWORD
#                   takes effect without undoing security changes an operator made as admin since.
# securityadmin needs the security index loaded, so wait for the plugin to report UP first. It and
# the health probe use localhost, which both bindings serve. Returns once the sync has succeeded; a
# failing sync is retried for as long as the node runs, with an ERROR in the log every report interval.
# Usage: sync_security_config SCOPE
sync_security_config() {
    local scope=$1
    local next_report=$((SECONDS + SECURITY_CONFIG_SYNC_REPORT_INTERVAL_SECONDS))
    local security_plugin_was_up=false
    local source_arguments
    if [[ "$scope" == all ]]; then
        source_arguments=(-cd "$SECURITY_CONFIG_DIR")
    else
        source_arguments=(-f "$INTERNAL_USERS_FILE" -t internalusers)
    fi
    while true; do
        if curl -s --max-time 5 --cacert "$TLS_CA_CERT" https://localhost:9200/_plugins/_security/health \
                | grep -q '"status":"UP"'; then
            security_plugin_was_up=true
            if timeout 60 bash "$SECURITY_TOOLS_DIR/securityadmin.sh" "${source_arguments[@]}" -icl \
                    -cacert "$TLS_CA_CERT" -cert "$TLS_ADMIN_CERT" -key "$TLS_ADMIN_KEY" \
                    > "$SECURITY_CONFIG_SYNC_LOG" 2>&1 \
                    && clear_ssl_dual_mode >> "$SECURITY_CONFIG_SYNC_LOG" 2>&1; then
                echo "SSL dual mode cluster setting cleared: the transport port accepts TLS only."
                break
            fi
        fi
        if (( SECONDS >= next_report )); then
            if [[ "$scope" == all ]]; then
                echo "ERROR: the security configuration is still not reset in the security index, or SSL dual mode not cleared; retrying. OpenSearch keeps listening on loopback only, so no other container can reach it." >&2
            else
                echo "ERROR: the internal users are still not synced into the security index, or SSL dual mode not cleared; retrying. The index was reset to admin only before, so no demo user is back, but a changed OPENSEARCH_PASSWORD is not in effect and the node reports unhealthy." >&2
            fi
            if [[ "$security_plugin_was_up" == true ]]; then
                cat "$SECURITY_CONFIG_SYNC_LOG" >&2
            else
                echo "The security plugin has not reported UP yet." >&2
            fi
            next_report=$((SECONDS + SECURITY_CONFIG_SYNC_REPORT_INTERVAL_SECONDS))
        fi
        sleep 5
    done
}

# Stops the processes, waits for the first (OpenSearch) to exit, and exits as a stopped container does.
# Usage: stop_and_exit OPENSEARCH_PID OTHER_PID...
stop_and_exit() {
    kill -TERM "$@" 2>/dev/null || true
    wait "$1" || true
    exit 143
}

reset_security_config() {
    sync_security_config all
    if ! touch "$SECURITY_CONFIG_RESET_FLAG"; then
        echo "ERROR: the security configuration is reset, but $SECURITY_CONFIG_RESET_FLAG cannot be written; OpenSearch stays on loopback only." >&2
        return 1
    fi
}

# Runs OpenSearch on loopback only until the security index is reset to the image's defaults with
# admin as the only user, then stops it, so the caller starts it again on all interfaces. The restart
# happens inside the container, which therefore neither exits nor depends on the restart policy. If
# the flag cannot be written, OpenSearch keeps running on loopback; if OpenSearch stops first, so does
# the container.
# Usage: run_on_loopback_until_reset [OPENSEARCH_ARGUMENTS...]
run_on_loopback_until_reset() {
    local opensearch_pid reset_pid finished_pid status=0
    write_opensearch_config _local_
    "$OPENSEARCH_HOME/opensearch-docker-entrypoint.sh" "$@" &
    opensearch_pid=$!
    reset_security_config &
    reset_pid=$!
    # docker stop reaches this shell through the init process, not OpenSearch: pass it on.
    # shellcheck disable=SC2064 # The process ids are known now and must not change.
    trap "stop_and_exit $opensearch_pid $reset_pid" TERM INT

    # Both are children of this shell, which keeps an exited child's status until it is waited for:
    # wait -n returns a job that exited before this call at once, with its pid and real status.
    wait -n -p finished_pid "$opensearch_pid" "$reset_pid" || status=$?
    if [[ "$finished_pid" == "$opensearch_pid" ]]; then
        kill -TERM "$reset_pid" 2>/dev/null || true
        echo "ERROR: OpenSearch stopped (status $status) before the security configuration was reset." >&2
        (( status != 0 )) || status=1
        exit "$status"
    fi
    if (( status != 0 )); then
        wait "$opensearch_pid" || status=$?
        exit "$status"
    fi

    echo "Security configuration reset to the image's defaults: admin is the only OpenSearch user. Restarting OpenSearch to listen on all interfaces."
    kill -TERM "$opensearch_pid"
    wait "$opensearch_pid" || true
    trap - TERM INT
}

rm -f "$INTERNAL_USERS_SYNCED_MARKER"
check_admin_password_strength
if [[ ! -d "$TLS_DIR" ]]; then
    echo "ERROR: $TLS_DIR is missing: docker-compose.yaml mounts it as a tmpfs owned by opensearch." >&2
    exit 1
fi
generate_tls_certificates
write_internal_users
# Otherwise the image entrypoint runs the demo installer, which brings back the demo users and,
# on a new container, the demo PKI.
export DISABLE_INSTALL_DEMO_CONFIG=true
# Otherwise the image entrypoint starts the performance analyzer agent, which serves metrics on port
# 9600 of every interface over plain HTTP without authentication, during the loopback phase too.
# EpicStaff does not use it.
export DISABLE_PERFORMANCE_ANALYZER_AGENT_CLI=true
if [[ ! -f "$SECURITY_CONFIG_RESET_FLAG" ]]; then
    echo "The security index is not yet known to hold only the image's default security configuration and EpicStaff's users (a new data volume, or one the demo configuration set up). OpenSearch listens on loopback only until it is reset, then restarts once."
    run_on_loopback_until_reset "$@"
fi
write_opensearch_config 0.0.0.0
# Also on the start that just reset the index: one path writes the healthcheck's marker.
# Double fork: the sync outlives this shell's exec into OpenSearch and is reparented to the init
# process (compose init: true), which reaps it when it finishes.
( {
    sync_security_config internal_users
    touch "$INTERNAL_USERS_SYNCED_MARKER"
    echo "Internal users synced: admin is the only OpenSearch user."
} & )

exec "$OPENSEARCH_HOME/opensearch-docker-entrypoint.sh" "$@"
