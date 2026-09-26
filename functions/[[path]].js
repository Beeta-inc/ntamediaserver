import { handleRequest, handleOptions } from "./_proxy.js";

export const onRequestOptions = handleOptions;
export const onRequest = handleRequest;
export const onRequestGet = handleRequest;
export const onRequestPost = handleRequest;
export const onRequestPut = handleRequest;
export const onRequestDelete = handleRequest;
export const onRequestPatch = handleRequest;
export const onRequestHead = handleRequest;
