# zram — compressão de swap em RAM
#
# memoryPercent=50: reserva no máximo 50% da RAM para zram compresso.
# Com zstd (ratio ~3:1), 50% de 32GB = 16GB de swap comprimido ≈ 48GB efetivos.
# swappiness=10 (em configuration.nix): prefere RAM livre, usa zram só em pressão.
{
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
    priority = 999;
  };
}
