import { Configuration, PublicClientApplication } from "@azure/msal-browser";

export const msalConfig: Configuration = {
  auth: {
    clientId: "a16dee1e-dafd-4334-8e4f-95212e9389b6",
    authority: "https://login.microsoftonline.com/4b443fe5-100a-489e-b6bb-b6685b55cd96",
    redirectUri: window.location.origin + "/auth/popup.html",
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage",
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const LOGIN_SCOPES = ["openid", "profile", "User.Read"];

export const GRAPH_SCOPES = [
  "https://graph.microsoft.com/Sites.Read.All",
  "https://graph.microsoft.com/Files.ReadWrite.All",
];
