{
  lib,
  config,
  ...
}:
# Qdrant Vector Database — infraestrutura base do RAG.
# Condicional a services.jarvis.enable (master toggle).
lib.mkIf config.services.jarvis.enable {
  users.groups.qdrant = {};

  users.users.qdrant = {
    isSystemUser = true;
    group = "qdrant";
    description = "Qdrant Vector Database Service User";
  };

  services.qdrant = {
    enable = true;
    settings = {
      storage = {
        storage_path = "/var/lib/qdrant/storage";
        snapshots_path = "/var/lib/qdrant/snapshots";
      };
      service = {
        http_port = 6333;
        grpc_port = 6334;
      };
    };
  };

  systemd.services.qdrant = {
    partOf = ["jarvis.target"];
    wantedBy = ["jarvis.target" "multi-user.target"];
    # 24/09: self-hosted sem api_key deixa qualquer processo local (e
    # qualquer agente) ler QUALQUER coleção — inclusive pessoal_code. A
    # chave vem de EnvironmentFile root:nixos 600, nunca do store do Nix.
    # 24/09 NOTA (auth do Qdrant deliberadamente desligada): o módulo NixOS
    # não aceita `environmentFiles` neste serviço, e usar `environment`
    # gravaria a api_key no Nix store (world-readable em
    # /etc/systemd/system) — proteção de fachada, que dá falsa sensação de
    # segurança. A proteção REAL dos dados é o payload cifrado
    # (core/rag_crypto.py) + chave fora do disco de estado. Quando
    #quisermos auth: Qdrant suporta api_key + JWT por coleção
    # (QDRANT__SERVICE__API_KEY / JWT_RBAC) via drop-in systemd gerenciado
    # em /run — implementar com o dono, não por Nix store.
  };

  systemd.tmpfiles.rules = [
    "d /var/lib/qdrant 0750 qdrant qdrant -"
    "d /var/lib/qdrant/storage 0750 qdrant qdrant -"
    "d /var/lib/qdrant/snapshots 0750 qdrant qdrant -"
    "h /var/lib/qdrant - - - - +C"
  ];
}
