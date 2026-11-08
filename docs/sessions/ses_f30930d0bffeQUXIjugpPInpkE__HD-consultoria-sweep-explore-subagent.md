# HD consultoria sweep (@explore subagent)

- **sessão:** `ses_f30930d0bffeQUXIjugpPInpkE`
- **quando:** 2026-09-23 18:00 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 11 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Inventário focado em /run/media/nixos/YUMI/PROJETOS/ (HD externo, read-only, NÃO mover/criar/deletar nada):
1. Liste 2 níveis de PROJETOS/CONSULTORIA/Aoop/ (foco: qualquer coisa ServiceNow, MID Server, credential, vault, JAR, Java, YAML de endpoints,Secrets). Depois as outras 10 pastas de consultoria em 1 nível + tamanhos (du -sh por pasta).
2. Liste 2 níveis de PROJETOS/PRODUTOS/ e PROJETOS/PESQUISA/ (linguagem, README, estado do código).
3. Procure por nomes de arquivo (NÃO conteúdo) com: servicenow, credential, vault, cyberark, mid, resolver, snc (use Glob/grep filename, ex.: "**/*[Ss]erviceNow*", "**/*.jar", "**/*.yaml").
REGRAS: só nomes de arquivos/diretórios e tamanhos. NUNCA imprima conteúdo de arquivos (podem ter segredos/NDA de clientes). Volte um relatório compacto: achados ServiceNow (paths), candidatos a produto (path+linguagem+estado), tamanhos por pasta.

---

## · ?

Inventário read-only concluído em `/run/media/nixos/YUMI/PROJETOS/` — só nomes/tamanhos, nenhum conteúdo aberto, nada criado/movido/deletado.

### 1. CONSULTORIA/Aoop — 2 níveis

**Nível 1 `Aoop/` (4,6G total):**
`___All_Errors.txt`, `Aoop Dados Clientes.txt`, `Upload File ServiceNow.txt`, `AoopJAMFUtils.js`, `compare groups.js`, `nb.js`, `__11 - Implementation/`, `__50 - Clientes/`, `11 - Implementation/`, `50 - Clientes/`, `90 - Outros/`, `ALM/`, `Aoop Cloud Solutions/`, `CredentialResolver/`, `ServiceNow/`, `VR/`, + docs/demissão/xls/ppt.

**Nível 2 (du -sh):**
- `50 - Clientes/` 3,1G | `11 - Implementation/` 851M | `ServiceNow/` 318M | `CredentialResolver/` 201M | `90 - Outros/` 110M | `VR/` 1,8M | `ALM/` 896K | `Aoop Cloud Solutions/` 512K | `__50/` 512K | `__11/` 256K
- `50 - Clientes/`: `0100 - BV/`, `0101 - Ailos/`, `0102 - Suzano/`, `0103 - Banco PAN/`, `0104 - Tribanco/`, `0108 - Vivo/`, `0109 - Cielo/`, `0111 - Bradesco/`, `0900 - Happy Customers/`, `Templates/`
- `11 - Implementation/`: `11 - Discovery/`, `31 - Event Management/`, `51 - SAM/`, `61 - Metric Intelligence/`, `71 - SecOps/`, `90 - NowCreate references/`, `91 - Labs/`, `92 - ALS References/`, `93 - Dev Files/`, `Instance Setup - AIOps.xmind`
- `ServiceNow/`: `CSA/` (Leo Quizlet, Prova V2, Simulados/), `Vivo/` (2 arquivos senhasegura), `Senha Segura.pdf`, `TACO- Free On Demand Training.pdf`, `Áreas de Script.ppsx`, docs admissão
- `ServiceNow/CSA/Simulados/`: `ServiceNow Fundamentals.xmind`, `Resumo ServiceNow[2370].pptx`, `Mastering ServiceNow.pdf`, etc.
- `CredentialResolver/`: `app/` (`bin/`, `build/`, `src/`, `build.gradle.kts`), `resources/` (`CredentialResolver$1.class`), `.gradle/`, `.vscode/`, `generate_jar.sh`, `settings.gradle.kts`, `SenhaSeguraBig.jar`, `CredentialResolver_20-09-2022.rar`
- `CredentialResolver/app/src/main/java/`: `com/snc/discovery/CredentialResolver.java` (+ `.class`), `jars/ehcache-3.10.0-jakarta.jar`, `org/ehcache|json|yaml/` (.class)
- `90 - Outros/`: `ITOM/`, `Discovery_getOverlapRanges.js`, `ServiceMapping.xlsx`, `ServiceNow Logos/`, `Squad Loom/MIDServer - Remote Access.txt`, etc.
- `ALM/`: 4 xlsx (`sys_user_group.xlsx`, `URLs.xlsx`...)
- `VR/`: `EFP-Banco Votorantim-SecOps Vulnerability Response-v1.0.docx`, `Processo.bpm/.pdf`, `Vulnerability Response - BV.xmind`
- `__11/`: só `91 - Labs_Error.txt` | `__50/`: só `0105 - Livelo/`

**Outras 10 pastas CONSULTORIA — 1 nível + `du -sh` (ordenado):**
- `Ailos/` 768K: `json.json`, `nbkp.js`, `restuser.ps1`, `send_snow_mid.sh`, `send_snow.sh`
- `BancoBV/` 256K: `JamfUtils.js`
- `Brick Abode/` 256K: `entrevista brick abode.txt`
- `Cielo/` 3,9M: `CertTest.ps1`, `NetWorkTestMidTovCenter.ps1`, `NetWorkTestMidTovCenter2.ps1`, `discovery_range_item.csv`, `Network Test Cielo`, `EVO/HML/RJO/SPO/*.txt`, `VMWARE*`, `*.png`
- `Fazenda da Mata/` 313M: `Artes/`, `Engenharia/`, `Ovos/`
- `Sonda/` 4,5G: `Técnico/`, `Técnico.7z`, `Desktop/`, `botbkp01.inventario`, `CRITICO-CVE-2023-38408-openssh-7010833.xlsm`
- `SpotDev/` 13M: `crawler.sh`, `STL/`, `lixo/`, `*.txt` (dicio/sinonimos/cam urls/btc)
- `Stefanini/` 1,5G: `docker-stuff/`, `docker-stuff.rar`, `COFRE.txt`, `DMZ.txt`, `ESX.txt`, `Servidores/`, `Suporte Unix/`, `Ferramentas T.I/`, etc.
- `Vivo/` 122M: `CredentialResolver/` (cópia evoluída, ver abaixo), `CredentialResolver.rar`, `SenhaSegura2.bpm`
- `µTech/` 1,7G: `Games/`, `Imagens/`, `Produtos/`, `Serviços/`

### 2. PRODUTOS + PESQUISA — 2 níveis

**`du -sh`:** `PESQUISA/LLM/` 1,0M | `PRODUTOS/Wurm Ultimate/` 5,9M | `PESQUISA/tibia_15_20_discoveries/` 13M | `PRODUTOS/MuDreamNotifier/` 199M | `PESQUISA/AI_SYSTEM/` 253M | `PRODUTOS/guia_renamer/` 1,7G | `PESQUISA/OTServer_UPGRADE/` 12G

- `PRODUTOS/guia_renamer/` — Python (`main.py`, `core/*.py`, `ui/main_window.py`, `requirements.txt`, `pyproject.toml`) | `README.md`+`BUILD.md`+`CHANGELOG.md`+`docs/`+`tests/`+`supabase/`+`landing/`+`.github/`+`build/`+`dist/`+`bin/` | Estado: produto maduro/buildado.
- `PRODUTOS/MuDreamNotifier/` — Python Windows (`mudream_notifier.py`, `license_generator.py`, `requirements.txt`, `MuDreamNotifier.spec`) | `README.md`+`CLAUDE.md` | Estado: buildado (`build/`, `dist/`, `dist_obf/`, `licencas/`).
- `PRODUTOS/Wurm Ultimate/` — Python (`main.py`, `core/`, `gui/`, `macros/`, `detection/`, `utils/`, `safety/`) | SEM `README.md` | Estado: código ativo sem docs.
- `PESQUISA/AI_SYSTEM/` — Python (`*.py`, `agents/`, `jarvis/`, `llm/`, `tools/`, `scripts/`, `tests/`) | `README.md`+`JARVIS.md`+`docs/` | Estado: pesquisa extensa ativa (136 entradas).
- `PESQUISA/LLM/` — Python (`hardware_detector.py`, `model_config.py`, `model_loader.py`, `old/`) | SEM `README.md` | Estado: esboço.
- `PESQUISA/OTServer_UPGRADE/` — misto (C++/Lua/Python: `canary/`, `otclient-mehah/`, `TibiaAPI/`, `protocol/`, `scripts/`, `tests/`, `tools/`, `www/`) | SEM `README.md` raiz, mas `CLAUDE.md`+`GEMINI.md`+`JOURNAL.md`+`docs/` | Estado: pesquisa ativa gigante.
- `PESQUISA/tibia_15_20_discoveries/` — pesquisa protocolo (`scripts/`, `proto/`, `opcodes/`, `connection/`, `encryption/`) | `README.md`+`PROTOCOL_TRUTH.md`+`INTEGRATION_GUIDE.md` | Estado: documentado.

### 3. Busca por NOME (Glob, sem conteúdo)

**ServiceNow (~40 hits, amostra):** `Aoop/Upload File ServiceNow.txt`, `Aoop/50 - Clientes/Templates/ServiceNow_ITOM_PoV_CLIENTE_v1.docx`, `Aoop/50 - Clientes/0101 - Ailos/89 - POC/ServiceNow_ITOM_PoV_Ailos_v*.docx`, `Aoop/50 - Clientes/0108 - Vivo/Proposta/VIVO - Project Kick-Off 31-01-2022 - ServiceNow ITSM e ITOM - V4.pdf`, `Aoop/11 - Implementation/90 - NowCreate references/San Diego/.../ServiceNow Operating Model.pdf`, `Aoop/50 - Clientes/0100 - BV/.../Arquitetura ServiceNow ITOM BV.drawio/.png`, `Aoop/50 - Clientes/0101 - Ailos/.../Arquitetura ServiceNow ITOM.drawio`, `Aoop/ServiceNow/CSA/Simulados/...`

**Credential/Resolver (núcleo JAR/Java):**
- `Aoop/CredentialResolver/app/src/main/java/com/snc/discovery/CredentialResolver.java` — único `.java` em Aoop, pacote `com.snc.discovery`
- `Vivo/CredentialResolver/app/src/main/java/com/snc/discovery/CredentialResolver.java` (duplicata/evolução)
- `Aoop/CredentialResolver/SenhaSeguraBig.jar`, `Aoop/CredentialResolver/app/src/main/java/jars/ehcache-3.10.0-jakarta.jar`
- `Vivo/CredentialResolver/app/src/main/java/SenhaSegura-PRD.jar`, `SenhaSegura-HML_DSV.jar`, `SenhaSegura-HML_DSV_WORKING.jar`, `SenhaSegura-HML_DSV_BACKUP.jar`, `jars/snakeyaml-1.30.jar`, `jars/json-simple-1.1.1.jar`, `jars/httpclient-4.5.13.jar`, `jars/httpcore-4.4.15.jar`
- `Vivo/CredentialResolver.rar`, `Aoop/CredentialResolver/CredentialResolver_20-09-2022.rar`
- Suzano credenciais: `Aoop/50 - Clientes/0102 - Suzano/.../012 Discovery/Credencial/discovery_credentials_*.xml` (8 arquivos)
- `Aoop/50 - Clientes/0101 - Ailos/.../RITM0199764 - Arrumar CredentiallessDiscovery.xml`

**SenhaSegura/vault/cofre ( Param principal de vault):**
- `Vivo/CredentialResolver/app/extlib/config.yml` — único YAML de endpoints relevante
- `Aoop/ServiceNow/Vivo/SenhaSegura 3.14 Developer.pdf`, `Aoop/ServiceNow/Vivo/Integração de API - senhasegura v1.2.pptx`
- `Aoop/50 - Clientes/0108 - Vivo/03 - Senha Segura/` (`Vivo - IntegraçãoSenhaSegura - V2.0.docx`, `SenhaSegura_v2.pptx`, `SenhaSegura2.bpm`), `.../Documentos Técnicos/ProTEC-ITOM-CofreSenha-SenhaSegura-Público.docx`
- `Stefanini/COFRE.txt` (só nome)
- `vault`, `cyberark`, `snc` como nome de arquivo: **zero hits**.

**MID Server:**
- `Ailos/send_snow_mid.sh`, `Ailos/send_snow.sh`
- `Cielo/NetWorkTestMidTovCenter.ps1`, `Cielo/NetWorkTestMidTovCenter2.ps1`
- `Aoop/11 - Implementation/11 - Discovery/MID Server Best Practices.pptx`
- `Aoop/50 - Clientes/0108 - Vivo/Documentos Técnicos/DocTech - MID Server - Discovery - Projeto Vivo_04_2022.pdf`
- `Aoop/50 - Clientes/0109 - Cielo/.../STRY0096141 - DIS - Validação Arquitetura MID Server e Tuning/` (`MID-Servers-Hosts.xlsx`, `MIDS-PROD/HML/DEV.png`)
- `Aoop/50 - Clientes/0111 - Bradesco/.../MID Server/Controle MID Servers.xlsx`, `.../ProTEC-ITOM-MID_Servers_v1.0.docx`
- `Aoop/50 - Clientes/0100 - BV/.../Arquitetura MID Servers ITOM BV-v2.drawio/.png`, `.../midserver-planning-checklist.xlsx`

**JAR/YAML geral CONSULTORIA:**
- `**/*.jar` (14): todos acima + `Vivo/CredentialResolver/gradle/wrapper/gradle-wrapper.jar`, `Sonda/Desktop/RemoteDroidServer/RemoteDroidServer.jar`
- `**/*.yml` (4): `Vivo/CredentialResolver/app/extlib/config.yml`, `Sonda/Técnico/Playbooks/Playbook vCenter Server Creation.yml`, 2x Stefanini grafana-zabbix
- `**/*.yaml` (só Stefanini docker-stuff, nada ServiceNow); `**/*.java` em Aoop: só o `CredentialResolver.java`.

**Resumo achados:** par `Aoop/CredentialResolver` + `Vivo/CredentialResolver` é o ativo ServiceNow/MID/credential/vault — Java `com.snc.discovery` + JARs SenhaSegura (PRD/HML) + `config.yml` só no Vivo.

---

