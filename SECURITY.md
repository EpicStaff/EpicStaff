# Security Policy

We take security issues in EpicStaff seriously, and we are grateful to the people
who report them to us.

## Reporting a vulnerability

**Please do not open a public GitHub issue for a security problem.** A public issue
tells everyone about the weakness at the same moment it tells us, which leaves
users exposed while a fix is being written.

Instead, email **security@epicstaff.com** with `SECURITY` in the subject line.

If you would rather not use email, you can use GitHub's private vulnerability
reporting on this repository (the **Report a vulnerability** button under the
*Security* tab), which opens a channel visible only to the maintainers.

### What to include

You do not need all of this, and a partial report is much better than no report.
The more of it you can give us, the faster we can act:

* What the problem is, and what an attacker could achieve with it.
* Which component is affected: a file path, service name, or endpoint.
* The version, tag, or commit you tested against, and whether it was a
  self-hosted deployment or a hosted one.
* Steps to reproduce, or a proof of concept.
* Anything you think we might get wrong when assessing the severity.

## Our commitment to good-faith researchers

If you make a good-faith effort to follow this policy, then:

* We will not pursue or support legal action against you for your research.
* We will not report you to law enforcement for it.
* We will treat your report as an authorised contribution to the security of the
  project, not as an attack on it.
* We will work with you on disclosure timing rather than dictating it.

We consider research to be in good faith when you:

* Only test against your own deployment, or against accounts and data you own or
  have explicit permission to use.
* Stop as soon as you have confirmed a vulnerability, and do not go further into
  the system than you need to in order to demonstrate it.
* Do not access, modify, exfiltrate, or destroy data belonging to anyone else,
  and tell us immediately if you encounter such data by accident.
* Do not degrade the service for others — no denial of service, no resource
  exhaustion, no spam or social engineering of our staff or users.
* Give us a reasonable opportunity to fix the issue before disclosing it
  publicly.

This is not a bug bounty programme. We do not offer payment for reports. We say
this plainly so that nobody spends their time expecting otherwise.

We will tell you when a fix ships, and we are happy to credit you by name or
handle in the release notes and any advisory. Tell us how you would like to be
credited, or that you would prefer not to be.

## Scope

In scope: the code in this repository, the container images we publish from it,
and the deployment configuration it ships.

Out of scope: findings that depend on a modified or misconfigured deployment
rather than on our defaults, vulnerabilities in third-party dependencies that
already have a published upstream advisory and no EpicStaff-specific impact
(report those upstream — though do tell us if we are slow to pick up the fix),
and reports produced by an automated scanner with no demonstrated impact.

If you are not sure whether something is in scope, report it anyway and let us
decide.

## Supported versions

We provide fixes for the latest release on the `main` branch. We do not backport
security fixes to older tags. If you run a pinned version, plan on being able to
move forward to take a fix.
