{ ...}:
# ═══════════════════════════════════════════════════════════════════════
# DISKO — partições declarativas do host (Acer Nitro V15, 2 NVMe)
# ═══════════════════════════════════════════════════════════════════════
{
  disko.devices = {
    disk = {
      # ── NVMe A (SM2P41C8): Sistema e Store Nix ──────────────────────
      system = {
        type = "disk";
        device = "/dev/disk/by-id/nvme-SM2P41C8-512GC1_0000_0000_0000_0000_707C_1800_2429_0100.";
        content = {
          type = "gpt";
          partitions = {
            ESP = {
              size = "1G";
              type = "EF00";
              content = {
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot";
                mountOptions = ["fmask=0077" "dmask=0077"];
              };
            };
            root = {
              size = "100%";
              content = {
                type = "btrfs";
                extraArgs = ["-f"];
                subvolumes = {
                  "/root" = {
                    mountpoint = "/";
                    mountOptions = ["compress=zstd" "noatime" "nodiratime" "discard=async" "commit=60"];
                  };
                  "/nix" = {
                    mountpoint = "/nix";
                    mountOptions = ["compress=zstd" "noatime" "nodiratime" "discard=async" "commit=60"];
                  };
                };
              };
            };
          };
        };
      };

      # ── NVMe B (ADATA): Home e Dados ─────────────────────────────────
      home = {
        type = "disk";
        device = "/dev/disk/by-id/nvme-IM2P33F3_NVMe_ADATA_512GB_0000_0000_0000_0000_707C_1800_0000_0001.";
        content = {
          type = "gpt";
          partitions = {
            home = {
              size = "100%";
              content = {
                type = "btrfs";
                extraArgs = ["-f"];
                subvolumes = {
                  "/home" = {
                    mountpoint = "/home";
                    mountOptions = ["compress=zstd" "noatime" "nodiratime" "discard=async" "commit=60"];
                  };
                };
              };
            };
          };
        };
      };
    };
  };
}
