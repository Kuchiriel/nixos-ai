# ═══════════════════════════════════════════════════════════════════════
# hardware-configuration.nix — PLACEHOLDER
#
# SUBSTITUA este arquivo pelo gerado no host real:
#
#   nixos-generate-config --root /mnt
#   cp /mnt/etc/nixos/hardware-configuration.nix ./hosts/nitro-v15/
#
# O gerado detecta: disco (NVMe), filesystem (btrfs/ext4), bootloader,
# CPU (i7-13620H) e GPUs (RTX 4050 + Intel UHD).
#
# NOTA: boot.loader já está declarado no configuration.nix —
# remova as linhas de boot do arquivo gerado para evitar conflito.
# ═══════════════════════════════════════════════════════════════════════
{ modulesPath, ... }:
{
  imports = [ (modulesPath + "/installer/scan/not-detected.nix") ];
}
