# Build e run testes C++ canary (@general subagent)

- **sessão:** `ses_ef197698fffeiPHXnLSVsS7vwW`
- **quando:** 2026-10-05 23:31 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 63 (exportadas: 23)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No repo /home/nixos/projects/canary-official, valide os testes C++ das mudanças recentes de RSA (2048 bits) e database (retry limitado). Contexto: src/security/rsa.cpp (fail-stop sem fallback), src/security/rsa_backend_mbedtls.cpp (RsaBlockSize 128→256, V1.5 explícito no setKey), src/server/network/protocol/protocol.cpp (janela 128→256), tests/fixture/security/rsa_test_vectors.hpp (vetores V1.5 256B novos), tests/unit/security/rsa_test.cpp + rsa_backend_equivalence_test.cpp (atualizados p/ throw), tests/fixture/security/key.pem (nova 2048).

Passos:
1. Leia docs/building/build-sem-vcpkg.md (ou equivalente) para o fluxo de build SEM vcpkg. O server já builda via `docker build -f docker/Dockerfile.sandbox --target build` (imagem canary:buildtest existe). Descubra como compilar os targets de teste (canary_it? unit tests?) — pode ser outro target/stage do mesmo Dockerfile ou cmake nativo.
2. Compile os testes. Se o build completo for inviável, compile ao menos os suites security + database.
3. Rode: tests/unit/security/*, tests/integration/security/* e o que existir de database. 
4. Devolva: O QUE buildou, PASS/FAIL por suite com os nomes dos testes que falharam (e a mensagem de falha), e se alguma falha indica erro NOS VETORES ou NO CÓDIGO de produção. NÃO edite código de produção; se um teste precisar de ajuste óbvio, descreva o ajuste em vez de aplicar. Seja terse.

---

## · ?

Validando RSA 2048 e retry da database — mapeando build e suítes.

---

## · ?

Vi o escopo das mudanças RSA/database. Agora vou localizar os targets de teste e verificar o ambiente de build.

---

## · ?

Sem cache local de build; imagem canary:buildtest existe. Vou inspecionar o conteúdo dela e mapear os testes de database.

---

## · ?

Container de build criado. Sincronizando fontes atuais para dentro dele.

---

## · ?

Fontes sincronizadas. Instalando gtest no vcpkg_installed do container.

---

## · ?

gtest instalado. Reconfigurando com CANARY_BUILD_TESTS=ON e compilando canary_ut + canary_it.

---

## · ?

gtest resolvido via cache binário. Copiando para a árvore do build e reconfigurando.

---

## · ?

GTestConfig presente. Reconfigurando o build com testes habilitados.

---

## · ?

Configure OK. Compilando canary_ut + canary_it (incremental).

---

## · ?

Build OK (só warning de deprecated). Rodando suites unit/security.

---

## · ?

connection.cpp mudou só logs. Pegando a mensagem exata da falha de Connection para julgar flaky vs real.

---

## · ?

Firewall bloqueia bridge→host. Criando rede dedicada entre os containers.

---

## · ?

Rede OK. Rodando canary_it: suite RSA + suites de database.

---

## · ?

Todos os 12 testes de database passaram. Parando os containers temporários e fechando o relatório.

---

## · ?

Validação concluída. Resumo terse:

## O QUE buildou
- Imagem `canary:buildtest` não tinha gtest nem `CANARY_BUILD_TESTS=ON`. Subi container `canary-testbuild`, sincronizei `src/ tests/ cmake/ CMakeLists.txt CMakePresets.json vcpkg.json schema.sql` do working tree, instalei gtest (via binary cache) e reconfigurei com `-DCANARY_BUILD_TESTS=ON -DVCPKG_MANIFEST_INSTALL=OFF`.
- **Targets compilados com sucesso**: `canary_ut` + `canary_it` (só warning de `pushUserdata` deprecated, pré-existente). Tropeço no caminho: meu primeiro `vcpkg install` em modo manifest limpou `/srv/vcpkg_installed` — restaurei de `/opt/vcpkg_installed` (intacto) e instalei gtest em modo `--classic`. Build final íntegro.
- DB de teste: `mariadb:11.4` próprio (`canary-testdb`, porta 3307 do host) + rede `canary-testnet`; schema.sql importado.

## Resultados
| Suite | Resultado |
|---|---|
| `canary_ut` full (344 tests) | **340 PASS, 4 FAIL** |
| `canary_ut` security (`Rsa*`) | 4 PASS, **3 FAIL** |
| `canary_it` `RsaIntegrationTest` | **1 FAIL** |
| `canary_it` `*RepositoryDBTest*` (12 tests: Account×9, PlayerStorage×3) | **12 PASS** |

Falhas (todas determinísticas, reproduzidas 2×):
1. `RsaBackendTest.RawDecryptMatchesExpectedFallbackOutput`, `.LoadPemFailureKeepsExistingKey`, `.SetKeyFailureKeepsExistingKey` — decrypt devolve `00 02 AB×221 00 M`, esperado era `M + zeros`.
2. `RsaIntegrationTest.StartLoadsPemAndDecryptsFallbackCompatibleBlock` — decrypt com `key.pem` devolve bloco pseudo-aleatório (`93 56 6B 6B…`), nada a ver com o esperado.
3. `ConnectionWriteDiagnosticsTest.WriteFailureRetainsPeerAndReportsClosureWithBoundedWarnings` — `unacceptedDiagnostics.back()` não contém `age_ms=-1` / `close_requested_by=none` (linhas 294–295). **Fora do escopo**: `connection.cpp` no diff tem só logs `[otc-net]` adicionados, e `writeDiagnostics()` filtra por `[Connection::onWriteOperation]` — falha é do budget de warnings vs expectativa do teste, não das mudanças RSA/database.

## Veredito: erro NOS VETORES/TESTES, não no código de produção
Prova matemática (Python, sem mexer no C++): `n = DefaultP×DefaultQ` tem 2048 bits; `pow(FixedInput, d, n)` = exatamente `00 02 AB×221 00 M`, com `M == ExpectedFixedOutput[:32]` e `RSAEP(EM) == FixedInput`. Ou seja, os vetores estão internamente consistentes **para decrypt RAW**. E produção está correta em ser RAW: `mbedtls_rsa_private()` ignora `set_padding` (só afeta as wrappers `pkcs1_*`), e `Protocol::RSA_decrypt` (`protocol.cpp:217`) **depende** do bloco cru — checa `msg.getByte() == 0` (o `00` do padding V1.5) e o login lê a XTEA logo depois. Se o backend fizesse unpad, o protocolo real quebraria. O comentário no `setKey` ("sem isto decrypt de teste e produção divergiriam") parte de premissa errada — os dois caminhos já eram e continuam RAW.
- Causa adicional da falha 2: `tests/fixture/security/key.pem` é **outra chave 2048** (`P*Q != n` do key.pem, verificado via parse DER) — mesmo com `ExpectedFixedOutput` corrigido, o IT seguiria falhando.

## Ajuste sugerido (não aplicado)
- Em `rsa_test_vectors.hpp`: `ExpectedFixedOutput` deve ser o bloco EM completo de 256B (`00 02 AB×221 00 M`), não `M + zeros`. Alternativa melhor: asserir estrutura (`[0]==0, [1]==2, PS≠0, separador 00, sufixo M`) em vez de bloco chapado.
- Regenerar `tests/fixture/security/key.pem` **a partir de** DefaultP/Q (ou vice-versa) para o IT fazer sentido; como está, ele descriptografa com chave errada.
- `database.cpp` (retry limitado): compila e os 12 ITs de DB passam, mas **nenhum teste cobre o caminho de retry-limite** (exigiria MySQL inalcançável + 10s de sleep) — só regressão do caminho feliz foi validada.

Containers `canary-testbuild` / `canary-testdb` + rede `canary-testnet` parados e mantidos para reinspeção; `data/` não foi sincronizado (assets do IT carregaram OK com o `data/` da imagem).

---

## · ?

Continuando sua validação anterior (containers canary-testbuild/canary-testdb + rede canary-testnet parados e mantidos). Duas mudanças no working tree desde então, ambas em /home/nixos/projects/canary-official:

1. tests/fixture/security/rsa_test_vectors.hpp REGENERADO a partir da chave do fixture (tests/fixture/security/key.pem): DefaultP/Q agora são p/q dessa chave; FixedInput = RSAEP(00 02 AB*221 00 M) e ExpectedFixedOutput = o bloco EM completo (decrypt é RAW — sua própria conclusão).
2. src/security/rsa_backend_mbedtls.cpp: removida a linha checkMbedTls(setRsaPadding(...)) do caminho setKey (era no-op enganoso).

Sincronize src/ + tests/ no container de build, recompile SÓ o necessário (canary_ut + canary_it) e rode: todos os Rsa* (unit) + RsaIntegrationTest (IT, com o testdb ligado). Devolva PASS/FAIL por teste. Se verde, também rode o canary_ut FULL para confirmar que nada mais quebrou (esperado: só o ConnectionWriteDiagnosticsTest pré-existente falha). Terse.

---

## · ?

Verificando o diff das duas mudanças e religando os containers.

---

## · ?

Vetores validados matematicamente contra o fixture. Sincronizando e recompilando.

---

## · ?

Build OK. Rodando Rsa* unit + RsaIntegrationTest.

---

## · ?

Unit RSA 7/7 verde. Rodando o IT.

---

## · ?

Tudo verde no RSA. Rodando canary_ut full.

---

## · ?

Verde no RSA. Resultado:

## Unit — `Rsa*` (7/7 PASS)
- `RsaBackendTest.RawDecryptMatchesExpectedFallbackOutput` — OK
- `RsaBackendTest.RawDecryptPreservesLeadingZerosIn256ByteBuffer` — OK
- `RsaBackendTest.DecryptWithoutLoadedKeyKeepsBufferUnchanged` — OK
- `RsaBackendTest.StartAbortsBootWhenPemIsMissing` — OK
- `RsaBackendTest.LoadPemFailureKeepsExistingKey` — OK
- `RsaBackendTest.SetKeyFailureKeepsExistingKey` — OK
- `RSATest.StartAbortsBootForMissingPemFile` — OK

## Integration — `RsaIntegrationTest` (1/1 PASS)
- `StartLoadsPemAndDecryptsFallbackCompatibleBlock` — OK (carrega `key.pem` 2048 real via `start()` e o bloco bate — fecha o loop fixture↔vetores↔backend)

## Full `canary_ut` — 343/344
Única falha: `ConnectionWriteDiagnosticsTest.WriteFailureRetainsPeerAndReportsClosureWithBoundedWarnings` — a mesma pré-existente, fora de escopo (expectativa de budget de warnings vs `back()` da lista; `connection.cpp` no diff só ganhou logs `[otc-net]`, que nem passam pelo filtro `[Connection::onWriteOperation]` do teste). Nenhuma outra regressão; a remoção do `setRsaPadding` no `setKey` não alterou comportamento observável (era no-op sobre `mbedtls_rsa_private`, como previsto).

Pré-checagem matemática confirmou antes do build: `DefaultP/Q == p/q` do `key.pem`, `raw-decrypt(FixedInput) == ExpectedFixedOutput`, `RSAEP(EO) == FixedInput`, `n` com 2048 bits.

Só recompilei `canary_ut` + `canary_it` (incremental: unity_23 + relink). Containers parados e mantidos.

---

