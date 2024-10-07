# Release Notes

This page provides high-level overviews of the dependencies and features that are supported by each revision in every stable release. To learn more about the different release tracks, see the [Juju documentation about risk levels](https://juju.is/docs/juju/channel?#heading--risk).

To see all releases and commits, check the [Charmed PgBouncer Releases page on GitHub](https://github.com/canonical/pgbouncer-operator/releases).

## Dependencies and supported features

For each release, this table shows:

* The PgBouncer version packaged inside
* The minimum Juju version required to reliably operate **all** features of the release
  > This charm still supports older versions of Juju 2.9. See the [system requirements](/t/12307) for more details
* Support for specific features

| Release| PgBouncer version | Juju version | [TLS encryption](/t/12310) | [COS monitoring](/t/12308) | [Minor version upgrades](/t/12317) |
|:---:|:---:|:---:|:---:|:---:|:---:|
|[394], [395], [396], [397]| `1.21.0` | `3.4.5+` | ![check] | ![check] | ![check]
|[278], [279], [280], [281]| `1.21.0` | `3.4.5+` | ![check] | ![check] | ![check]
|[254], [255], [256], [257]| `1.21.0` | `3.1.8+` | ![check] | ![check] | ![check]
|[173], [174], [175], [176]| `1.21.0` | `3.1.8+` | ![check] | ![check] | ![check]
|[88], [89] | `1.21.0` | `3.1.7+`| | ![check] | ![check]
|[80], [81] | `1.21.0` | `3.1.6+`| | ![check] | ![check]
|[76], [77]| `1.18.0` | `3.1.6+` | | ![check] | ![check]

## Architecture and base

Due to the [subordinate](https://juju.is/docs/sdk/charm-taxonomy#heading--subordinate-charms) nature of this charm, several [revisions](https://juju.is/docs/sdk/revision) are released simultaneously for different [bases/series](https://juju.is/docs/juju/base) using the same charm code. In other words, one release contains multiple revisions.

> If you do not specify a revision on deploy time, Juju will automatically choose the revision that matches your base and architecture.

> If you deploy a specific revision, **you must make sure it matches your base and architecture** via the tables below or with [`juju info`](https://juju.is/docs/juju/juju-info).

### Release 394-397 (`1/stable`)
| Revision | `amd64` | `arm64` | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:-----:|:--------:|:--------:|:-----:|:-----:|
| [394] |          | ![check] | ![check] |          |
| [395] | ![check] |          | ![check] |          |
| [396] | ![check] |          |          | ![check] |
| [397] |          | ![check] |          | ![check] |

[details=Release 278-281]

| Revision | `amd64` | `arm64` | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:-----:|:--------:|:--------:|:-----:|:-----:|
| [278] | ![check] |          |          | ![check] |
| [279] | ![check] |          | ![check] |          |
| [280] |          | ![check] |          | ![check] |
| [281] |          | ![check] | ![check] |          |

[/details]

[details=Release 254-257]

| Revision | `amd64` | `arm64` | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:-----:|:--------:|:--------:|:-----:|:-----:|
| [254] |          | ![check] | ![check] |          |
| [255] | ![check] |          | ![check] |          |
| [256] | ![check] |          |          | ![check] |
| [257] |          | ![check] |          | ![check] |

[/details]

[details=Release 173-176]

| Revision | `amd64` | `arm64` | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:-----:|:--------:|:--------:|:-----:|:-----:|
| [173] |          | ![check] |          | ![check] |
| [174] | ![check] |          |          | ![check] |
| [175] | ![check] |          | ![check] |          |
| [176] |          | ![check] | ![check] |          |

[/details]

[details=Release 88-89]

| Revision | amd64 | arm64 | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:----:|:--------:|:--------:|:-----:|:-----:|
| [89] | ![check] |          | ![check] |          |
| [88] | ![check] |          |          | ![check] |

[/details]

[details=Release 80-81]

| Revision | amd64 | arm64 | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:----:|:--------:|:--------:|:-----:|:-----:|
| [81] | ![check] |          |          | ![check] |
| [80] | ![check] |          | ![check] |          |

[/details]

[details=Release 76-77]

| Revision | amd64 | arm64 | Ubuntu 20.04 (focal) | Ubuntu 22.04 (jammy)
|:----:|:--------:|:--------:|:-----:|:-----:|
| [77] | ![check] |          | ![check] |          |
| [76] | ![check] |          |          | ![check] |

[/details]

<br>

[note]
 Our release notes are an ongoing work in progress. If there is any additional information about releases that you would like to see or suggestions for other improvements, don't hesitate to contact us on [Matrix ](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or [leave a comment](https://discourse.charmhub.io/t/pgbouncer-reference-release-notes/12285).
[/note]

<!--LINKS-->
[394]: /t/15379
[395]: /t/15379
[396]: /t/15379
[397]: /t/15379
[394, 395, 396, 397]: /t/15379
[278]: /t/14853
[279]: /t/14853
[280]: /t/14853
[281]: /t/14853
[254]: /t/14666
[255]: /t/14666
[256]: /t/14666
[257]: /t/14666
[173]: /t/14069
[174]: /t/14069
[175]: /t/14069
[176]: /t/14069
[89]: /t/13126
[88]: /t/13126
[81]: /t/12766
[80]: /t/12766
[77]: /t/12286
[76]: /t/12286

<!-- BADGES -->
[check]: https://img.icons8.com/color/20/checkmark--v1.png