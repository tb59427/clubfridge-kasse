# Drittanbieter-Lizenzen – Clubfridge Kasse Image

## Python-Pakete

| Paket | Version | Lizenz | URL |
|-------|---------|--------|-----|
| Kivy | 2.3.1 | MIT | http://kivy.org |
| Kivy-Garden | 0.1.5 | MIT | https://github.com/kivy-garden |
| Pygments | 2.19.2 | BSD | https://pygments.org |
| RPi.GPIO | 0.7.1 | MIT | http://sourceforge.net/projects/raspberry-gpio-python/ |
| SQLAlchemy | 2.0.48 | MIT | https://www.sqlalchemy.org |
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.12.1 | MIT | https://anyio.readthedocs.io |
| certifi | 2026.2.25 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.4.6 | MIT | https://github.com/jawah/charset_normalizer |
| docutils | 0.22.4 | BSD / GPL / Public Domain | https://docutils.sourceforge.io |
| evdev | 1.9.3 | BSD-3-Clause | https://github.com/gvalkov/python-evdev |
| filetype | 1.2.0 | MIT | https://github.com/h2non/filetype.py |
| greenlet | 3.3.2 | MIT / PSF-2.0 | https://greenlet.readthedocs.io |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| idna | 3.11 | BSD-3-Clause | https://github.com/kjd/idna |
| pydantic | 2.12.5 | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.13.1 | MIT | https://github.com/pydantic/pydantic-settings |
| pydantic_core | 2.41.5 | MIT | https://github.com/pydantic/pydantic-core |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| requests | 2.32.5 | Apache-2.0 | https://requests.readthedocs.io |
| structlog | 25.5.0 | MIT / Apache-2.0 | https://github.com/hynek/structlog |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| urllib3 | 2.6.3 | MIT | https://github.com/urllib3/urllib3 |

## System-Pakete (Raspberry Pi OS / Debian Trixie)

Das Image enthält Systempakete aus den offiziellen Debian- und
Raspberry-Pi-Paketquellen. Eine vollständige Liste der installierten Pakete
mit ihren Lizenzen ist auf dem laufenden System verfügbar über:

```bash
dpkg-query -W -f='${Package} ${Version} ${License}\n'
```

Die Lizenztexte der einzelnen Pakete befinden sich unter:

```
/usr/share/doc/<paketname>/copyright
```

### Wesentliche Systemkomponenten

| Komponente | Lizenz |
|-----------|--------|
| Linux Kernel | GPL-2.0 |
| glibc | LGPL-2.1 |
| systemd | LGPL-2.1 |
| Python 3.13 | PSF-2.0 |
| SDL2 | Zlib |
| Mesa (OpenGL) | MIT |
| NetworkManager | GPL-2.0 |
| OpenSSH | BSD |
| GStreamer | LGPL-2.0 |

## Vollständige Lizenztexte

Die vollständigen Texte der verwendeten Lizenzen sind verfügbar unter:

- **MIT**: https://opensource.org/licenses/MIT
- **BSD-3-Clause**: https://opensource.org/licenses/BSD-3-Clause
- **Apache-2.0**: https://www.apache.org/licenses/LICENSE-2.0
- **GPL-2.0**: https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
- **LGPL-2.1**: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- **MPL-2.0**: https://www.mozilla.org/en-US/MPL/2.0/
- **PSF-2.0**: https://docs.python.org/3/license.html
- **Zlib**: https://opensource.org/licenses/Zlib
