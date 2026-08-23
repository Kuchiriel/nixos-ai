{...}: {
  programs.git = {
    enable = true;
    settings = {
      user.email = "matheus.almeida211094@gmail.com";
      user.name = "Kuchiriel";
      init.defaultBranch = "main";
      http.sslVerify = true;
    };
  };
}
