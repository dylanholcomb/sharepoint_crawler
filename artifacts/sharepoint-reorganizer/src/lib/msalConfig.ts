import { Configuration, PopupRequest, PublicClientApplication } from "@azure/msal-browser";

export const msalConfig: Configuration = {
  auth: {
    clientId: "a16dee1e-dafd-4334-8e4f-95212e9389b6",
    authority: "https://login.microsoftonline.com/4b443fe5-100a-489e-b6bb-b6685b55cd96",
    redirectUri: window.location.origin + "/auth/redirect",
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage",
    storeAuthStateInCookie: false,
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const loginRequest: PopupRequest = {
  scopes: [
    "User.Read",
    "https://graph.microsoft.com/Sites.Read.All",
    "https://graph.microsoft.com/Files.ReadWrite.All",
  ],
};
