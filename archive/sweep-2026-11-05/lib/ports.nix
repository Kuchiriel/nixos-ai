# Port management utilities
#
# This module provides functions to manage service ports across multiple hosts
# in a centralized way. Ports are defined in your configuration and can have
# host-specific overrides.
#
# Usage in your configuration:
#
#   # In your flake or configuration, define your ports:
#   let
#     projectLib = ...;
#
#     myPorts = {
#       ports = {
#         nginx = 80;
#         grafana = 3000;
#         prometheus = 9090;
#         homepage = 8080;
#       };
#       hostPorts = {
#         laptop = {
#           nginx = 8080;  # Override nginx port on laptop
#         };
#         server = {
#           homepage = 3001;  # Override homepage port on server
#         };
#       };
#     };
#
#     portHelpers = projectLib.ports.mkPortHelpers myPorts;
#   in {
#     # Use in your config:
#     services.nginx.port = portHelpers.getPort "nginx" "laptop";
#     # Returns: 8080 (host-specific override)
#
#     services.grafana.port = portHelpers.getPort "grafana" "laptop";
#     # Returns: 3000 (default port)
#
#     # Get all ports for a specific host (defaults + overrides):
#     allLaptopPorts = portHelpers.getHostPorts "laptop";
#     # Returns: { nginx = 8080; grafana = 3000; prometheus = 9090; homepage = 8080; }
#   }
{lib}: {
  # Create port helper functions from a ports configuration
  #
  # Args:
  #   portsConfig: An attribute set with structure:
  #     {
  #       ports = { service-name = port-number; ... };
  #       hostPorts = { hostname = { service-name = port-number; ... }; ... };
  #     }
  #
  # Returns:
  #   An attribute set containing helper functions:
  #     - getPort: Get port for a service with optional host override
  #     - getHostPorts: Get all ports for a specific host
  #     - listServices: List all defined services
  mkPortHelpers = portsConfig: let
    ports = portsConfig.ports or {};
    hostPorts = portsConfig.hostPorts or {};
  in {
    # Get port for a service, with optional host-specific override
    #
    # Args:
    #   service: The service name (string)
    #   host: The hostname (string)
    #
    # Returns:
    #   Port number (int) or null if service not found
    #
    # Example:
    #   getPort "nginx" "laptop"  # Returns host-specific port if defined
    #   getPort "nginx" null      # Returns default port
    getPort = service: host:
      if host != null && hostPorts ? ${host} && hostPorts.${host} ? ${service}
      then hostPorts.${host}.${service}
      else ports.${service} or null;

    # Get all ports for a specific host (merges defaults with host overrides)
    #
    # Args:
    #   host: The hostname (string)
    #
    # Returns:
    #   Attribute set of all ports for the host
    #
    # Example:
    #   getHostPorts "laptop"  # { nginx = 8080; grafana = 3000; ... }
    getHostPorts = host:
      ports // (hostPorts.${host} or {});

    # List all defined service names
    #
    # Returns:
    #   List of service names (strings)
    listServices = lib.attrNames ports;
  };
}
