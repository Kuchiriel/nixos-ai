nix-shell -p cryptsetup --run "sudo cryptsetup open /dev/sdb2 manjaro-rescue"
nix-shell -p coreutils --run "sudo mkdir -p /mnt/manjaro"
nix-shell -p util-linux --run "sudo mount /dev/mapper/manjaro-rescue /mnt/manjaro"
