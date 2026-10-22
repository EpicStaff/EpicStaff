# Security model

What the plugin platform protects, and who it trusts with what: SuperAdmins, plugin publishers, plugin code, the
organizations a plugin is granted to, and the people in them. Each statement links the page it rests on, which has the
details. What the platform does not protect against is in [Accepted risks](accepted-risks.md).

## Plugins are open code

> Plugins are meant to be open code, and EpicStaff does not check that they are. Anyone who can reach a deployment can download a plugin's frontend files. Every administrator of every deployment that installs a plugin can read the whole package, including its backend code. EpicStaff is not responsible for that exposure.

So a package holds nothing its publisher would not publish. `epicstaff-plugin pack`, `validate` and EpicStaff's upload
refuse a package with an EpicStaff key or a runtime file in it ([Keep secrets out of a
package](../how-to/sign-and-package.md#keep-secrets-out-of-a-package)).

## Trust

- **Only SuperAdmins install plugins.** They upload a package, read its review, approve it and grant it to
  organizations ([Sign and package a plugin](../how-to/sign-and-package.md#6-hand-it-over)).
- **The review shows what the plugin asks for:** its declared access in EpicStaff, each with the publisher's reason,
  the permissions it gives people, its public paths, its outbound hosts, its database, its settings, its limits and
  hooks, and its signature, with warnings where a declaration deserves a second look
  ([Manifest and package format](../reference/manifest.md), [review warnings](../reference/manifest.md#review-warnings)).
- **Trusted and Untrusted say who signed the package**, not what its code does. A package signed with a key the
  deployment lists is Trusted; any other is Untrusted, and approving it needs an explicit acknowledgement. Both can do
  exactly the same once approved ([Trust and signing](trust-and-signing.md#trusted-is-a-label-not-a-permission)).
- **More access takes another approval.** A new version that declares more access, a new outbound host or a wider
  public path cannot be installed until a SuperAdmin approves that new access
  ([Compatibility and versioning](../reference/compatibility-and-versioning.md#what-needs-the-superadmins-approval)).
  Approving the outbound hosts does not limit what code run through flows or tools can reach.
- **Installing a plugin means trusting its code**, whichever label it has
  ([Accepted risks](accepted-risks.md#installing-a-plugin-means-trusting-its-code)).

## Plugins on one node

- **Each backend is kept to itself.** It runs as its own process, under a Unix user of its own, with its own virtual
  environment, its own writable directory and its own runtime file, which no other plugin can read
  ([Runtime](../reference/runtime.md#other-plugins-on-the-same-node)).
- **Some things are still visible.** Every plugin on the node can list the processes with their command lines, see the
  listening ports and which plugins are installed, and connect to another plugin's port. So secrets never go on a
  command line, and every request a backend serves must carry a gateway context or a hook call EpicStaff signed, which
  no other plugin can forge; the Python SDK refuses everything else before it reaches the plugin's code
  ([Runtime](../reference/runtime.md#other-plugins-on-the-same-node),
  [Gateway context](../reference/gateway-context.md#verification)).
- **Shared ports, watched.** The plugins share the node's ports. A plugin cannot bind one, its connections are capped,
  and the node stops a plugin that has a TCP socket listening on any port or holds more than 1,280 network sockets, within a
  second, until a SuperAdmin restarts it ([Runtime](../reference/runtime.md#how-the-backend-is-started),
  [Accepted risks](accepted-risks.md#what-co-located-plugins-can-see-of-each-other)).
- **The separation is the operating system's.** Every backend of a node runs in one container, separated by process
  and user permissions only: a plugin that gets past its own user's permissions reaches the others on that node
  ([Accepted risks](accepted-risks.md#plugins-on-one-node-share-a-container)).

## Organizations

- **One organization at a time.** Every gateway context of a person names one organization, a public path's context
  names none, and every service-account key belongs to one organization. A call that names another organization, or a
  row of one, is answered 404, as if it did not exist ([Gateway context](../reference/gateway-context.md#format),
  [Service account API](../reference/service-account-api.md#calling-epicstaff)).
- **Inside the plugin it is the plugin's job.** One backend and one database serve every organization the plugin is
  granted to. Keeping their data apart there is the plugin's code: a transaction per organization with the SDK's
  `org_transaction`, under row-level security
  ([Write database migrations](../how-to/database-migrations.md#6-keep-organizations-apart-with-row-level-security),
  [Accepted risks](accepted-risks.md#keeping-organizations-apart-inside-a-plugin-is-the-plugins-job)).

## What a plugin can do in EpicStaff

- **Exactly its declared access**, in each organization it is granted to, through EpicStaff's own endpoints. That
  access reaches every item of the declared type in the organization, apart from secrets, of which it may use only
  the ones it created. A run it starts, and an indexing job, are refused when a model configuration's headers name
  another secret ([Declare what your backend may do](../how-to/declare-access.md#what-the-declaration-does-not-give),
  [Accepted risks](accepted-risks.md#declared-access-covers-every-item-of-a-type)).
- **Never EpicStaff's administration.** Organizations, memberships, roles, API keys, the audit log and chats cannot be
  declared, and the endpoints only people use refuse a plugin ([Manifest](../reference/manifest.md#access)).
- **"On behalf of" is the plugin's statement.** EpicStaff checks only that the person is an active member who may use
  the plugin in the organization, and still allows only the plugin's declared access. A plugin checks the person's own
  rights through the people endpoint before it does something for them they could not do themselves
  ([Service account API](../reference/service-account-api.md#on-behalf-of-a-person)).
- **Org Admins see it.** Each organization's Plugin activity lists the plugins acting there, with their declared
  access, and every change they made, with the person they acted for
  ([Activity](../reference/service-account-api.md#activity)).

## In the browser

- **Each plugin has an origin of its own**, `<id>.<plugins base domain>`, and only EpicStaff may frame its page
  ([Frame protocol](../reference/frame-protocol.md#the-frame)).
- **A plugin's page cannot use EpicStaff's API.** EpicStaff refuses any request whose origin is a plugin host, except
  the sign-in's authorize navigation and code exchange ([Token exchange](../reference/token-exchange.md#what-a-plugin-page-cannot-do)).
- **The plugin login token stays in the page.** The JS SDK keeps it in memory only and sends it only to the plugin's
  own `/api/`. It lives 15 minutes, works nowhere but the plugin's gateway, and never reaches the plugin's backend,
  which gets a gateway context instead ([Using the token](../reference/token-exchange.md#using-the-token),
  [Gateway context](../reference/gateway-context.md#who-is-asking-user-contexts)).
- **No cookies cross the gateway**, in either direction: a backend never gets the browser's cookies, and the browser
  never gets cookies a plugin sets ([Gateway context](../reference/gateway-context.md#how-a-request-reaches-the-plugin)).
- **HTTPS**, everywhere but a deployment on your own machine on `.localhost` names. On HTTPS, EpicStaff's login cookie
  is `__Host-auth.refresh`, which no plugin host can set
  ([Sign-in and EpicStaff's login cookie](../operator/enable-plugins.md#sign-in-and-epicstaffs-login-cookie)).
- **Frame messages are checked.** EpicStaff and the page each accept the other's messages only from the expected
  window and origin, and nothing secret travels over them ([Handshake](../reference/frame-protocol.md#handshake)).

## Network

- **Without sign-in, only declared public paths** reach the backend, each within its body cap and rate limit
  ([Serve public paths](../how-to/public-paths.md)).
- **Outbound, only to declared hosts**, over HTTPS on port 443, through the egress proxy, and a change to the list
  applies within about 30 seconds ([Call the internet from your backend](../how-to/outbound-hosts.md)). The backend's
  own process has no other route out. Code that a plugin gets run through flows or tools is the exception: see the next item.
- **Flows and tools run code.** A plugin whose access includes `create`, `update` or `use` on flows, or `create` or
  `update` on tools, can have code of its choosing run in EpicStaff's sandbox. The sandbox has its own network access,
  and the plugin's outbound hosts do not apply to that code. Tools `create` or `update` also lets it point an agent at
  an MCP server outside its outbound hosts ([Accepted risks](accepted-risks.md#code-runs-in-the-sandbox-outside-the-outbound-hosts)).
- **A declared host can carry more than its name.** A host on a shared content delivery network, or a `*.` wildcard,
  reaches more sites than its name says ([What an allow-list does not
  stop](../how-to/outbound-hosts.md#what-an-allow-list-does-not-stop)).
- **EpicStaff only through one door.** A backend cannot reach EpicStaff's other services, or EpicStaff and other
  plugins the way a browser does. It reaches EpicStaff's API only through the internal listener, and its keys work
  nowhere else ([How plugin backends are kept apart](../operator/enable-plugins.md#how-plugin-backends-are-kept-apart)).

## Data

- **Each plugin has its own database and roles.** None of the roles is a superuser or may bypass row-level security,
  and no plugin's roles can connect to another plugin's database ([Plugin database](../reference/database.md#roles)).
- **Limits.** The connection limit is hard. The statement timeout is a default of the plugin's role, which the
  platform puts back when it is changed ([Plugin database](../reference/database.md#limits)).
- **Secret settings** are stored encrypted, and decrypted only into a runtime file
  ([Use settings](../how-to/settings.md#secrets)).
- **Backups** are taken before an upgrade runs migrations, and hold every organization's data in the database
  ([Backups and restores](../reference/database.md#backups-and-restores),
  [Accepted risks](accepted-risks.md#backups-hold-every-organizations-data)).
- **Deleting data.** After the grace period, or when a SuperAdmin asks, EpicStaff deletes everything the plugin created
  in the organization, and asks the plugin to delete its own data
  ([The plugin lifecycle](lifecycle.md#when-the-grace-period-ends)).

## Suspension and removal

- **Suspending a plugin in an organization** stops its keys there at once, people's access within about 10 seconds,
  and every run that uses what it owns there ([What a suspension stops](lifecycle.md#what-a-suspension-stops)). Some
  things go on ([What a suspension does not stop](lifecycle.md#what-a-suspension-does-not-stop)).
- **Uninstalling** suspends it in every organization, stops its process and serves none of its paths
  ([Uninstall and reinstall](lifecycle.md#uninstall-and-reinstall)).
- **Deleting it** deletes every organization's data, then its database, code and files, and keeps its activity
  ([Deleting a plugin](lifecycle.md#deleting-a-plugin)).

## Development mode

- **Only on your own machine.** With plugin development mode on, django_app refuses to start unless
  `DJANGO_DEBUG=true`, EpicStaff's host is `localhost` or a `.localhost` name, the plugin base domain is a
  `.localhost` name, and the stack runs with `src/docker-compose.plugins-dev.yaml`; epicstaff-nginx refuses the same
  way (exit 64). What keeps the mode local is that file's binding of EpicStaff's ports to `127.0.0.1`. The
  `.localhost` names only stop browsers on other machines: a client that reaches a port can set the `Host` header by
  hand ([Plugin development mode](../operator/enable-plugins.md#plugin-development-mode)).
- **What it opens:** EpicStaff's development API listener, published only on that machine's `127.0.0.1`. It refuses
  callers from the plugin network; other containers that share a network with epicstaff-nginx can reach it. The
  only plugin credential it accepts is a development key. It also serves person tokens and anonymous endpoints,
  which the same callers already reach on port 80, so it gives them nothing more. The file also gives django_app the name `host.docker.internal`, and publishes EpicStaff's
  ports 80 and 443 on `127.0.0.1` only, so nobody else on the network reaches a plugin address that serves the
  machine's ports ([Plugin development mode](../operator/enable-plugins.md#plugin-development-mode)).
- **Only ports, only on that machine.** A SuperAdmin enters only ports: plugin traffic goes only to
  `host.docker.internal`, after every check the gateway always makes
  ([Plugin development mode](../operator/enable-plugins.md#plugin-development-mode)).
- **Development keys** work only through the development API listener and only while the mode is on; node keys do not
  work there. Stopping development, downloading the runtime file again and suspending the plugin in an organization
  revoke them; resuming issues none
  ([Development keys](../reference/service-account-api.md#development-keys)).
- **A development backend has no outbound allow-list** and does not use the plugin's own database
  ([A development backend](../reference/runtime.md#a-development-backend)).
- **A page from a development server** never gets the browser's cookies or `Authorization`, and cannot set cookies or
  frame rules of its own ([Develop the page against a development
  server](../how-to/local-development.md#develop-the-page-against-a-development-server)).
- **Turning it off** makes every stored development target and every development key inert, without deleting them
  ([Plugin development mode](../operator/enable-plugins.md#plugin-development-mode)).

## Accepted risks

The limits of all of the above, which an operator weighs before installing a plugin, are in
[Accepted risks](accepted-risks.md).
