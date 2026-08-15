{
  description = "My system configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-24.11";
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager/release-24.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    stylix = {
      url = "github:danth/stylix/release-24.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, home-manager, stylix, ... }@inputs: let
    system = "x86_64-linux";
    user = "nixos";

    hosts = [
      {
        hostname = "nixos-lab";
        stateVersion = "24.11";
      }
    ];

    makeSystem = { hostname, stateVersion }: nixpkgs.lib.nixosSystem {
      inherit system;
      specialArgs = {
        inherit inputs stateVersion hostname user;
      };

      modules = [
        {
          nixpkgs.config.allowUnfree = true;
          nixpkgs.overlays = [
            (final: prev: {
              llama-cpp = nixpkgs-unstable.legacyPackages.${prev.system}.llama-cpp;
            })
          ];
        }

        ./hosts/${hostname}/configuration.nix
        stylix.nixosModules.stylix

        home-manager.nixosModules.home-manager {
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.extraSpecialArgs = {
            inherit user;
            homeStateVersion = stateVersion;
          };
          home-manager.users.${user} = {
            imports = [
              ./home-manager/home.nix
              stylix.homeManagerModules.stylix
            ];
          };
        }
      ];
    };

  in {
    nixosConfigurations = nixpkgs.lib.foldl' (configs: host:
      configs // {
        "${host.hostname}" = makeSystem {
          inherit (host) hostname stateVersion;
        };
      }) {} hosts;
  };
}
