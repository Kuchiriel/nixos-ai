sudo nixos-rebuild switch --flake .#nitro-v15
sudo systemctl restart llama-cpp-server
sleep 8
journalctl -u llama-cpp-server --since "1 min ago" --no-pager
