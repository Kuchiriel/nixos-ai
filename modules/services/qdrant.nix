{
  lib,
  config,
  mkIf,
  ...
}: {
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

  systemd.tmpfiles.rules = [
    "d /var/lib/qdrant 0750 qdrant qdrant -"
    "d /var/lib/qdrant/storage 0750 qdrant qdrant -"
    "d /var/lib/qdrant/snapshots 0750 qdrant qdrant -"
  ];
}
