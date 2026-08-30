export const KEYWORD_SCHEMA_VERSION=1;
export const KEYWORD_STORAGE_KEY="korbklar.productKeywords.v1";

export function normalizeKeywords(values){
  const unique=new Map();
  for(const raw of Array.isArray(values)?values:[]){
    const value=String(raw??"").replace(/\s+/g," ").trim().slice(0,80);
    if(value&&!unique.has(value.toLocaleLowerCase("de")))unique.set(value.toLocaleLowerCase("de"),value);
    if(unique.size>=50)break;
  }
  return [...unique.values()];
}

export function keywordDocument(values){return {version:KEYWORD_SCHEMA_VERSION,keywords:normalizeKeywords(values)}}

export function parseKeywordDocument(text){
  let value;
  try{value=JSON.parse(String(text))}catch{throw new Error("Die Datei enthält kein gültiges JSON.")}
  if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("Die Schlagwortdatei muss ein JSON-Objekt sein.");
  if(value.version!==KEYWORD_SCHEMA_VERSION)throw new Error(`Nicht unterstützte Schlagwort-Version: ${String(value.version??"fehlt")}.`);
  if(!Array.isArray(value.keywords))throw new Error("Das Feld „keywords“ muss eine Liste sein.");
  return normalizeKeywords(value.keywords);
}

export function matchesProductName(name,values){
  const keywords=normalizeKeywords(values).map(value=>value.toLocaleLowerCase("de"));
  return !keywords.length||keywords.some(keyword=>String(name??"").toLocaleLowerCase("de").includes(keyword));
}
