{ ... }: {
  programs.git = {
    enable = true;
    userEmail = "matheus.almeida211094@gmail.com";
    userName = "Kuchiriel";

    # Se você tiver configurações personalizadas adicionais além do nome/email, 
    # use o bloco extraConfig abaixo (antigo initExtra):
    extraConfig = {
      init.defaultBranch = "main";
      http.sslVerify = true;
    };
  };
}
