# Boot loader — systemd-boot + EFI
# ÚNICA FONTE DE VERDADE para configuração de boot.
# configuration.nix NÃO deve duplicar essas configurações.
{
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
}
