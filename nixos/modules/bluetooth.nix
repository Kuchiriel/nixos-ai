{
  hardware.bluetooth.enable = true;
  hardware.bluetooth.powerOnBoot = true;
  hardware.bluetooth.settings = {
    General = {
      Reconnect = true;
      Mode = "powered";
      PairingMode = "multiple";
    };
    Policy = {
      AutoEnable = true;
    };
  };
  services.blueman.enable = true;
}
