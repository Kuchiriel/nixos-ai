# Segredos declarativos (sops-nix) — autorizado por d0010=Sim.
# A chave privada age fica em /var/lib/sops-nix/key.txt (root 600, fora do
# repo e do Nix Store). O arquivo secrets/litellm-env.yaml e criptografado.
{ config, ... }:
{
  sops = {
    age.keyFile = "/var/lib/sops-nix/key.txt";
    defaultSopsFile = ../secrets/litellm-env.yaml;
    secrets."litellm_env" = {
      path = "/etc/litellm-sops.env";
      owner = "root";
      group = "root";
      mode = "0600";
    };
  };

  # Garante que o servico so pode ler o segredo apos o sops-install-secrets.
  systemd.services.litellm.after = [ "sops-install-secrets.service" ];
  systemd.services.litellm.requires = [ "sops-install-secrets.service" ];
}
