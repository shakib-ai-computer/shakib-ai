# NOTICE — Upstream projects & licenses

SHAKIB AI integrates three upstream open-source projects. It does **not**
vendor or merge their code into this repository (except where a license and
the architecture plan explicitly allow library use); each component keeps its
own license and attribution.

| Component | Role in SHAKIB AI | License | Source |
|---|---|---|---|
| muhtalhakhan/open-agent | Internal agent service (tools / browser / computer-use tasks), invoked by Core | MIT | https://github.com/muhtalhakhan/open-agent |
| QuantumNous/new-api | Central model gateway — runs **unmodified** as its own container; SHAKIB AI uses only its public HTTP API | **AGPL-3.0** | https://github.com/QuantumNous/new-api |
| assafelovic/gpt-researcher | Deep-research engine, embedded as a Python library inside the Core service | Apache-2.0 | https://github.com/assafelovic/gpt-researcher |

## AGPL-3.0 consequence (new-api)

Because new-api is AGPL-3.0, offering the combined system as a public network
service triggers copyleft obligations for new-api itself (source availability
to its users, including any modifications). SHAKIB AI is therefore planned and
published as open source. No closed-source or "free/unlimited" hosted edition
is planned. This is an engineering record of the constraint, not legal advice;
re-confirm before any public launch.

Full license texts live in the upstream repositories linked above; they are
not reproduced here.
