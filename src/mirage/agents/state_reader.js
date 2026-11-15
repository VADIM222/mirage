// Mirage's read-only process adapter. Gameplay is never invoked here; ADB owns input.
// Native configuration iterators only read data on the game thread; no game Lua calls.
'use strict';
const library=Process.getModuleByName('libEz.so');
if(Process.pointerSize!==8)throw new Error('This profile requires a 64-bit Lua process');
const api={};
function pointer(name){
 const result=library.getExportByName(`_ZN2ez3lua${name.length}${name}E`).readPointer();
 const range=Process.findRangeByAddress(result);
 if(result.isNull()||range===null||!range.protection.includes('x'))throw new Error(`Lua API is not initialized: ${name}`);
 return result;
}
function bind(name,result,args){api[name]=new NativeFunction(pointer(name),result,args);}
bind('gettop','int',['pointer']);bind('settop','void',['pointer','int']);
bind('gettype','int',['pointer','int']);bind('pushnil','void',['pointer']);
bind('pushlstring','void',['pointer','pointer','ulong']);
bind('rawget','void',['pointer','int']);bind('rawgeti','void',['pointer','int','int']);
bind('next','int',['pointer','int']);bind('tonumber','double',['pointer','int']);
bind('toboolean','int',['pointer','int']);bind('tolstring','pointer',['pointer','int','pointer']);
bind('topointer','pointer',['pointer','int']);
bind('getmetatable','int',['pointer','int']);
bind('iscfunction','int',['pointer','int']);
bind('tocfunction','pointer',['pointer','int']);
bind('touserdata','pointer',['pointer','int']);
bind('pushnumber','void',['pointer','double']);
bind('pushvalue','void',['pointer','int']);
bind('pcall','int',['pointer','int','int','int']);
bind('replace','void',['pointer','int']);
const stateSlot=library.getExportByName('_ZN2ez3lua1LE');
const queue=[];
let busy=false;
let queueActivity=null;
let queueActivityObject=null;
const activityGetters=new Map();
const unitConfigCache=new Map();
const donationConfigCache=new Map();
const passConfigCache=new Map();
const tutorialConfigCache=new Map();
const buildingConfigCache=new Map();
const techniqueCatalogCache=new Map();
const constructionConfigCache=new Map();
const types=['nil','boolean','lightuserdata','number','string','table','function','userdata','thread'];

function scalar(L,index){
 const type=api.gettype(L,index);
 if(type===0)return null;
 if(type===1)return api.toboolean(L,index)!==0;
 if(type===3){const value=api.tonumber(L,index);return Number.isFinite(value)?value:null;}
 if(type===4){
  const size=Memory.alloc(8);size.writeU64(0);
  const text=api.tolstring(L,index,size);const length=Number(size.readU64());
  if(length>16384)return {$type:'string',truncated:true,length};
  if(text.isNull())return null;
  try{return text.readUtf8String(length);}
  catch(error){return {$type:'binary',length};}
 }
 return {$type:types[type]||String(type)};
}
function readTable(L,index,depth,budget,seen){
 const identity=api.topointer(L,index).toString();
 if(seen.has(identity))return {$cycle:true};
 seen.add(identity);
 const output={};
 api.pushnil(L);
 while(api.next(L,index)!==0){
  const keyType=api.gettype(L,-2);
  let key=null;
  if(keyType===3)key=String(api.tonumber(L,-2));
  if(keyType===4)key=scalar(L,-2);
  const valueType=api.gettype(L,-1);
  if(typeof key==='string'&&key!=='__proto__'&&valueType!==6&&valueType!==8){
   if(valueType===5&&depth>0)output[key]=readTable(L,api.gettop(L),depth-1,budget,seen);
   else output[key]=scalar(L,-1);
  }
  api.settop(L,api.gettop(L)-1);
  if(--budget.left<=0){api.settop(L,api.gettop(L)-1);output.$truncated=true;break;}
 }
 seen.delete(identity);
 return output;
}
function readPath(L,path,depth,budget){
 const base=api.gettop(L);
 try{
    if(path[0]==='@visible_views')return visibleViews(L);
     if(path[0]==='@item_counts')return itemCounts(L);
     if(path[0]==='@commander_config')return commanderConfig(L,Number(path[1]));
      if(path[0]==='@commander_text')return commanderText(L,path[1]);
      if(path[0]==='@player')return playerWithCommanders(L,depth,budget);
    if(path[0]==='@lucerne')return lucerneState(L);
     if(path[0]==='@tutorial')return tutorialState(L);
     if(path[0]==='@tutorial_step'){
      if(typeof path[1]!=='string'||!/^[A-Za-z0-9_]{1,100}$/.test(path[1]))return null;
      const cfg=rawPath(L,['GameDatas','tutorial_config_'+path[1]]);
      return cfg===null?null:tutorialStepConfig(L,cfg,Number(path[2]));
     }
     if(path[0]==='@reward_rows'){
      const id=Number(path[1]);return Number.isSafeInteger(id)&&id>0?cachedRewardRows(L,id):null;
     }
    if(path[0]==='@onboarding_battle')return onboardingBattle(L);
     if(path[0]==='@building_plan')return buildingPlan(L);
      if(path[0]==='@building_preview')return buildingPreview(L);
      if(path[0]==='@construction_plan')return constructionPlan(L);
       if(path[0]==='@vip_config')return vipConfig(L);
       if(path[0]==='@vip_daily_points'){
        const day=readPath(L,['VipData','ContinuousLogin'],0,{left:1});
        const config=rawPath(L,['GameDatas','vip_VIP_point']);
        return config===null||!Number.isSafeInteger(day)?null:tutorialStepConfig(L,config,day+1);
       }
     if(path[0]==='@research_plan')return researchPlan(L,path[1]);
     if(path[0]==='@research_form')return researchForm(L);
     if(path[0]==='@research_ui'){
      const out={tree:null};
      for(const name of ['ReseachPage_Economy','ReseachPage_Military']){
       const panel=rawPath(L,['UIObjectManager',name]);
       if(panel!==null&&api.gettype(L,panel)===5&&viewActive(L,panel,name)){
        out.tree=name;out.offset=fieldValue(L,panel,'GotoRate',0);
        out.width=fieldValue(L,panel,'m_UICullWidth',0);out.height=fieldValue(L,panel,'m_UICullHeigth',0);
       }
      }
      return out;
     }
     if(path[0]==='@side_quests')return sideQuests(L);
     if(path[0]==='@hud_functions')return hudFunctions(L);
     if(path[0]==='@resource_pack_ui')return resourcePackUI(L);
     if(path[0]==='@tavern_slg_hero'){
      const hero=rawPath(L,['UIObjectManager','AllUIHeroCheckIn_SLG']);
      const out={visible:hero!==null&&api.gettype(L,hero)===5&&viewActive(L,hero,'AllUIHeroCheckIn_SLG')};
      if(out.visible)for(const [key,name] of [['id','ShowHeroId'],['star','ShowHeroStar'],['width','m_UICullWidth'],['height','m_UICullHeigth']])
       out[key]=fieldValue(L,hero,name,0);
      return out;
     }
   if(path[0]==='@queue_panel')return queuePanel(L);
   if(path[0]==='@building_menu')return buildingMenu(L);
   if(path[0]==='@training_form')return trainingForm(L);
   if(path[0]==='@training_queues')return trainingQueues(L);
   if(path[0]==='@city_camera')return cityCamera(L);
   if(path[0]==='@wall_ui')return wallUI(L);
   if(path[0]==='@city_resources')return cityResources(L);
    if(path[0]==='@alliance_donation')return allianceDonation(L);
    if(path[0]==='@material_ui')return materialUI(L);
    if(path[0]==='@training_keyboard')return trainingKeyboard(L);
    if(path[0]==='@gather_target'){
     const id=readPath(L,['UIObjectManager','ResDepositPopUp','TargetId'],0,{left:1});
     if(!Number.isSafeInteger(id)||id<=0)return null;
     return readPath(L,['MapData','chars',id],3,{left:256});
    }
     if(path[0]==='@place_target')return discoveredPlaceTarget(L);
     if(path[0]==='@barbarian_target')return barbarianTarget(L);
     if(path[0]==='@barbarian_hold'){
      const getter=rawPath(L,['WorldMapHandler','SetStayAfterBattle']);
      const capture=getter===null?null:capturedData(L,getter,1,2);
      return capture===null||api.gettype(L,capture.index)!==5?null:fieldValue(L,capture.index,'stayAfterBattle',0);
     }
     if(path[0]==='@gather_troops')return readPath(L,['WorldMapData','MyChars','AllTroops'],5,{left:4096});
     if(path[0]==='@barbarian_armies')return barbarianArmies(L);
     if(path[0]==='@barbarian_scene')return barbarianScene(L);
      if(path[0]==='@barbarian_hero')return barbarianHero(L,path.length>1?Number(path[1]):3,path.length>2?Number(path[2]):0);
    if(path[0]==='@mail_summary')return mailSummary(L);
    if(path[0]==='@cave_mails')return caveMailRows(L);
   if(path[0]==='@active_view'){
    if(path.length!==2)return null;
    const index=rawPath(L,['UIObjectManager',path[1]]);
    return index===null||api.gettype(L,index)!==5?false:viewActive(L,index,path[1]);
   }
  if(path[0]==='@buildings')return buildings(L);
  let index=-10002;
  for(const key of path){
   if(api.gettype(L,index)!==5)return null;
   if(typeof key==='number'){
    if(!Number.isSafeInteger(key))return null;
    if(key>=-2147483648&&key<=2147483647)api.rawgeti(L,index,key);
    else {api.pushnumber(L,key);api.rawget(L,index);}
   }
   else {const bytes=Memory.allocUtf8String(key);api.pushlstring(L,bytes,unescape(encodeURIComponent(key)).length);api.rawget(L,index);}
   index=api.gettop(L);
  }
  return api.gettype(L,index)===5?readTable(L,index,depth,budget,new Set()):scalar(L,index);
 }finally{api.settop(L,base);}
}
function pushField(L,index,key){
 const bytes=Memory.allocUtf8String(key);
 api.pushlstring(L,bytes,unescape(encodeURIComponent(key)).length);api.rawget(L,index);
 return api.gettop(L);
}
function fieldValue(L,index,key,depth){
 const top=api.gettop(L);
 try{const value=pushField(L,index,key);return api.gettype(L,value)===5?readTable(L,value,depth,{left:20},new Set()):scalar(L,value);}
 finally{api.settop(L,top);}
}
function rawPath(L,path){
  let index=-10002;
  for(const key of path){
   if(api.gettype(L,index)!==5)return null;
   if(typeof key==='number'){
    if(!Number.isSafeInteger(key))return null;
    api.pushnumber(L,key);api.rawget(L,index);index=api.gettop(L);
   }else if(typeof key==='string')index=pushField(L,index,key);
   else return null;
  }
  return index;
}
function itemCounts(L){
 const base=api.gettop(L);
 try{
  if(readPath(L,['ItemData','MyItemListInited'],0,{left:1})!==true)return {ready:false,items:{}};
  const list=rawPath(L,['ItemData','MyItemList']);
  if(list===null||api.gettype(L,list)!==5)return {ready:false,items:{}};
  const items={},seen=new Set();let scanned=0;api.pushnil(L);
  while(api.next(L,list)!==0){
   if(++scanned>2048||api.gettype(L,-1)!==5)return {ready:false,items:{}};
   const row=api.gettop(L),id=fieldValue(L,row,'itemId',0),count=fieldValue(L,row,'itemCount',0);
   if(!Number.isSafeInteger(id)||id<=0||!Number.isSafeInteger(count)||count<0
       ||seen.has(id))return {ready:false,items:{}};
   seen.add(id);
   // Ignore zero cache entries: removal versus retention of an empty row is
   // not a real inventory delta. No configuration userdata or text is copied.
   if(count>0)items[String(id)]=count;
   api.settop(L,api.gettop(L)-1);
  }
  return {ready:true,items};
 }finally{api.settop(L,base);}
}
function barbarianTarget(L){
 const base=api.gettop(L);
 try{
  let id=null;
  for(const [name,key,scale] of [['SendTroopsMain','DstCharId',100],['MapUISelectTroops','CurTargetId',1],['MapUIBarbarianPopUp','TargetId',1]]){
   const panel=rawPath(L,['UIObjectManager',name]);
   if(panel!==null&&api.gettype(L,panel)===5&&viewActive(L,panel,name)){
    const value=fieldValue(L,panel,key,0);
    if(!Number.isSafeInteger(value)||value<=0||!Number.isSafeInteger(value*scale))return null;
    id=value*scale;break;
   }
  }
  if(id===null)return null;
  const chars=rawPath(L,['MapData','chars']);if(chars===null||api.gettype(L,chars)!==5)return null;
  api.pushnumber(L,id);api.rawget(L,chars);const target=api.gettop(L);if(api.gettype(L,target)!==5)return null;
   const out={};for(const key of ['id','charType','playerId','allianceId','isFighting','barbarianType','isFteVillage','pos'])
    out[key]=fieldValue(L,target,key,key==='pos'?1:0);
  out.npcInfo=readPath(L,['MapData','chars',id,'npcInfo'],1,{left:32});
  out.units=readPath(L,['MapData','chars',id,'troop','units'],2,{left:64});
  out.hp=readPath(L,['MapData','chars',id,'square','hp'],0,{left:1});
  out.hpMax=readPath(L,['MapData','chars',id,'square','hpMax'],0,{left:1});
   out.owner=readPath(L,['WorldMgr','allObjs',id,'playerId'],0,{left:1});
   out.config=out.npcInfo?barbarianConfig(L,out.npcInfo.npcType):null;
   out.layout={};
   for(const key of ['offset_x','offset_y','atkBtnY','stayToggleY'])
    out.layout[key]=readPath(L,['UIObjectManager','MapUIBarbarianPopUp',key],0,{left:1});
   const select=['UIObjectManager','MapUISelectTroops'],popup=['UIObjectManager','TroopSelectedPopUp'];
   const index=readPath(L,[...select,'selectIndex'],0,{left:1});
   out.selection={index,popupIndex:readPath(L,[...popup,'selectIndex'],0,{left:1}),
    target:readPath(L,[...select,'CurTargetId'],0,{left:1}),
    popupTarget:readPath(L,[...popup,'CurTargetId'],0,{left:1}),
    actualCost:readPath(L,[...popup,'ActualCost'],0,{left:1}),
    travel:readPath(L,[...popup,'troopMoveTime'],0,{left:1}),
    offensive:readPath(L,[...select,'isOffensive'],0,{left:1}),
    multi:readPath(L,[...select,'isMultiSelectMode'],0,{left:1}),
    popupMulti:readPath(L,[...popup,'isMultiSelectMode'],0,{left:1}),
    buyAP:readPath(L,[...popup,'ShowPveAPBuy'],0,{left:1})};
   if(Number.isSafeInteger(index)&&index>0&&index<=9){
     out.selection.row=barbarianTroopIdentity(L,[...select,'ListData',index,'troopInfo']);
    out.selection.rowType=readPath(L,[...select,'ListData',index,'type'],0,{left:1});
   }
   return out;
 }finally{api.settop(L,base);}
}
function barbarianScene(L){
 const base=api.gettop(L);
 try{
  const chars=rawPath(L,['MapData','chars']);if(chars===null||api.gettype(L,chars)!==5)return null;
  const out={};let scanned=0;api.pushnil(L);
  while(api.next(L,chars)!==0){
   const row=api.gettop(L);if(++scanned>2048)return null;
   if(api.gettype(L,row)===5&&fieldValue(L,row,'charType',0)===1){
    const id=fieldValue(L,row,'id',0),owner=fieldValue(L,row,'playerId',0);
    if(Number.isSafeInteger(id)&&id>0){
     const result={};for(const key of ['id','playerId','isFighting','pos','npcInfo'])
      result[key]=fieldValue(L,row,key,1);
     if(owner===-2&&result.npcInfo)result.config=barbarianConfig(L,result.npcInfo.npcType);
     const square=pushField(L,row,'square');
     if(api.gettype(L,square)===5){
      result.hp=fieldValue(L,square,'hp',0);result.hpMax=fieldValue(L,square,'hpMax',0);
     }
     const object=rawPath(L,['WorldMgr','allObjs']);
     if(object!==null&&api.gettype(L,object)===5){
      api.pushnumber(L,id);api.rawget(L,object);const obj=api.gettop(L);
      if(api.gettype(L,obj)===5){
       result.owner=fieldValue(L,obj,'playerId',0);
       result.attackTarget=fieldValue(L,obj,'attackTargetId',0);
       result.attackers=readPath(L,['WorldMgr','allObjs',id,'attackers'],2,{left:128});
      }
     }
     out[String(id)]=result;
    }
   }
   api.settop(L,row-1);
  }
  return out;
 }finally{api.settop(L,base);}
}
function barbarianArmies(L){
 const base=api.gettop(L);
 try{
  const rows=readPath(L,['WorldMapData','MyChars','AllTroops'],5,{left:4096});
  if(rows===null||typeof rows!=='object'||Object.keys(rows).some(k=>k.startsWith('$')))return null;
  const popup=rawPath(L,['UIObjectManager','AttackPopup']);let ui=null;
  if(popup!==null&&api.gettype(L,popup)===5&&viewActive(L,popup,'AttackPopup')){
   const info=pushField(L,popup,'CurShowInfo');if(api.gettype(L,info)!==5)return null;
   const button=pushField(L,info,'btn2');if(api.gettype(L,button)!==5)return null;
   const cb=pushField(L,button,'cb'),recall=pushField(L,popup,'RecallTroop');
   ui={target:fieldValue(L,popup,'targetId',0),buttons:fieldValue(L,info,'cnt',0),
    recall:api.gettype(L,cb)===6&&api.gettype(L,recall)===6&&api.topointer(L,cb).equals(api.topointer(L,recall)),
    icon:fieldValue(L,button,'icon',0),camera:cityCamera(L)};
  }
  for(const row of Object.values(rows))row.ui=ui;
  return rows;
 }finally{api.settop(L,base);}
}
function projectedConfig(L,path,index,wanted){
 const base=api.gettop(L);
 try{
  const configs=rawPath(L,path);if(configs===null||api.gettype(L,configs)!==7||api.getmetatable(L,configs)===0)return null;
  const getter=pushField(L,api.gettop(L),'__index');if(!dataReader(L,getter))return null;
  api.pushvalue(L,configs);api.pushnumber(L,index);if(api.pcall(L,2,1,0)!==0)return null;
  const row=api.gettop(L);if(api.gettype(L,row)!==7||api.getmetatable(L,row)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');if(!dataReader(L,pairs))return null;
  api.pushvalue(L,row);if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;if(!dataReader(L,iterator))return null;
  const output={};
  for(let count=0;count<128;count++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0)return null;
   if(api.gettype(L,-2)===0)return wanted.every(k=>Object.prototype.hasOwnProperty.call(output,k))?output:null;
   const name=scalar(L,-2);
   if(wanted.includes(name)){
    if(![0,1,3,4].includes(api.gettype(L,-1)))return null;
    output[name]=scalar(L,-1);
   }
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  return null;
 }finally{api.settop(L,base);}
}
const commanderConfigCache=new Map();
function playerWithCommanders(L,depth,budget){
 const base=api.gettop(L);
 try{
  const player=readPath(L,['UserData'],depth,budget);
  if(!player||!Number.isSafeInteger(player.PlayerID)||player.PlayerID<=0)return player;
  player._commanders={ready:false,player:player.PlayerID,heroes:{}};
  const heroes=rawPath(L,['HeroHandler','HeroMap']);if(heroes===null||api.gettype(L,heroes)!==5)return player;
  const out={};let count=0;api.pushnil(L);
  while(api.next(L,heroes)!==0){
   const row=api.gettop(L);if(++count>256||api.gettype(L,row)!==5)return player;
   const id=fieldValue(L,row,'Id',0),level=fieldValue(L,row,'Level',0),star=fieldValue(L,row,'Star',0);
   if(!Number.isSafeInteger(id)||id<1||id>1000000||!Number.isSafeInteger(level)||level<1||level>100
       ||!Number.isSafeInteger(star)||star<1||star>10||scalar(L,row-1)!==id)return player;
   const config=commanderConfig(L,id),name=config&&commanderText(L,config.LC_N);
   if(typeof name!=='string'||name.length>160)return player;
   out[String(id)]={id,name,level,star,rarity:config.Rare,tags:config.Tag,state:fieldValue(L,row,'State',0)};
   api.settop(L,row-1);
  }
  player._commanders={ready:true,player:player.PlayerID,heroes:out};return player;
 }finally{api.settop(L,base);}
}
function commanderText(L,key){
 const base=api.gettop(L);
 try{
  if(typeof key!=='string'||!/^LC_HERO_(NAME|NICKNAME)_\d+$/.test(key))return null;
  // The installed GameRoot_GetText wrapper names this native data reader.
  // Call only its string lookup; never the Lua wrapper or a Unity text getter.
  const getter=rawPath(L,['eng','rawGetGameText']);if(getter===null||!dataReader(L,getter))return null;
  const bytes=Memory.allocUtf8String(key);api.pushlstring(L,bytes,key.length);
  if(api.pcall(L,1,1,0)!==0||api.gettype(L,-1)!==4)return null;
  const value=scalar(L,-1);return typeof value==='string'&&value.length>0&&value!==key?value:null;
 }finally{api.settop(L,base);}
}
function commanderConfig(L,id){
 const base=api.gettop(L);
 try{
  if(!Number.isSafeInteger(id)||id<1||id>1000000)return null;
  const config=rawPath(L,['GameDatas','hero_Hero']);
  if(config===null||api.gettype(L,config)!==7||api.getmetatable(L,config)===0)return null;
  const identity=api.touserdata(L,config).toString()+':'+id;
  if(commanderConfigCache.has(identity))return commanderConfigCache.get(identity);
  const getter=pushField(L,api.gettop(L),'__index');
  if(dataReader(L,getter)){
   api.pushvalue(L,config);api.pushnumber(L,10000+id*10+1);
   if(api.pcall(L,2,1,0)===0){
    const direct=nativeScalarRow(L,api.gettop(L));
    if(direct&&direct.HeroID===id&&direct.Star===1){commanderConfigCache.set(identity,direct);return direct;}
   }
  }
  api.settop(L,config);
  if(api.getmetatable(L,config)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');if(!dataReader(L,pairs))return null;
  api.pushvalue(L,config);if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;if(!dataReader(L,iterator))return null;
  for(let count=0;count<8192;count++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0||api.gettype(L,-2)===0)return null;
   const row=api.gettop(L);
   if(configScalarField(L,row,'HeroID')===id&&configScalarField(L,row,'Star')===1){
    if(api.getmetatable(L,row)===0)return null;
    const rowPairs=pushField(L,api.gettop(L),'__pairs');if(!dataReader(L,rowPairs))return null;
    api.pushvalue(L,row);if(api.pcall(L,1,3,0)!==0)return null;
    const next=api.gettop(L)-2,context=next+1,cursor=next+2;if(!dataReader(L,next))return null;
    const output={};
    for(let n=0;n<256;n++){
     api.pushvalue(L,next);api.pushvalue(L,context);api.pushvalue(L,cursor);
     if(api.pcall(L,2,2,0)!==0)return null;
     if(api.gettype(L,-2)===0){commanderConfigCache.set(identity,output);return output;}
     const name=scalar(L,-2),type=api.gettype(L,-1);
     if(typeof name==='string'&&name!=='__proto__'&&[0,1,3,4].includes(type))output[name]=scalar(L,-1);
     api.pushvalue(L,api.gettop(L)-1);api.replace(L,cursor);api.settop(L,cursor);
    }
    return null;
   }
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  return null;
 }finally{api.settop(L,base);}
}
const skillGeometryCache=new Map();
function skillClient(L,id){
 const base=api.gettop(L);
 try{
  if(!Number.isSafeInteger(id)||id<=0)return null;
  const config=rawPath(L,['GameDatas','skill_Client']);
  if(config===null||api.gettype(L,config)!==7||api.getmetatable(L,config)===0)return null;
  const identity=api.touserdata(L,config).toString()+':'+id;
  if(skillGeometryCache.has(identity))return skillGeometryCache.get(identity);
  const pairs=pushField(L,api.gettop(L),'__pairs');if(!dataReader(L,pairs))return null;
  api.pushvalue(L,config);if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;if(!dataReader(L,iterator))return null;
  for(let i=0;i<8192;i++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0||api.gettype(L,-2)===0)return null;
   const row=api.gettop(L);
   if(configScalarField(L,row,'ID')===id){
    const out=nativeScalarRow(L,row);
    if(out)skillGeometryCache.set(identity,out);return out;
   }
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  return null;
 }finally{api.settop(L,base);}
}
function commanderGeometry(L,hero){
 const skill=hero.Skills&&hero.Skills['1'];
 const client=skill?skillClient(L,skill.SkillId):null;
 const area=client&&Number.isSafeInteger(client.AREA_ID)?projectedConfig(L,['GameDatas','skill_Area'],client.AREA_ID,
   ['AreaID','Angle','Radius','MaxTar','AreaType','Target']):null;
 return {client,area};
}
function barbarianHero(L,primary,deputy){
 const base=api.gettop(L);
 try{
   if(!Number.isSafeInteger(primary)||primary<1||primary>1000000||!Number.isSafeInteger(deputy)
       ||deputy<0||deputy>1000000||primary===deputy)return null;
   const hero=readPath(L,['HeroHandler','HeroMap',primary],4,{left:1024});
   if(hero===null||typeof hero!=='object'||hero.Id!==primary||hero.$truncated)return null;
   hero.selectedHeroes={'1':primary};
   if(deputy){
    hero.deputy=readPath(L,['HeroHandler','HeroMap',deputy],4,{left:1024});
    if(!hero.deputy||hero.deputy.Id!==deputy||hero.deputy.$truncated)return null;
    hero.selectedHeroes['2']=deputy;
    hero.deputy.chain=commanderGeometry(L,hero.deputy);
   }
  hero.pveTalent=barbarianPveTalent(L,hero);
  hero.dispatch=barbarianDispatchUi(L);
  const city=readPath(L,['WorldMapData','MyChars','CityId'],0,{left:1});
   hero.chain={...commanderGeometry(L,hero),
     scene:barbarianScene(L),reports:barbarianReports(L),camera:barbarianCamera(L),
    emptyPos:readPath(L,['UIObjectManager','MapEmptySpacePopUp','pos'],1,{left:8}),
   cityPos:Number.isSafeInteger(city)?readPath(L,['MapData','chars',city,'pos'],1,{left:8}):null};
  return hero;
 }finally{api.settop(L,base);}
}
function barbarianTroopIdentity(L,path){
 const base=api.gettop(L);
 try{
  const row=rawPath(L,path);if(row===null||api.gettype(L,row)!==5)return null;
  const out={};
  for(const key of ['troopId','charId','state','APR']){
   const value=fieldValue(L,row,key,0);
   if(!Number.isSafeInteger(value)||value<0)return null;
   out[key]=value;
  }
  return out;
 }finally{api.settop(L,base);}
}
function barbarianDispatchUi(L){
 const base=api.gettop(L);
 try{
  const ui=rawPath(L,['UIObjectManager','SendTroopsMain']);
  const city=ui!==null&&api.gettype(L,ui)===5&&viewActive(L,ui,'SendTroopsMain');
  const selector=rawPath(L,['UIObjectManager','MapUISelectTroops']);
  if(!city&&(selector===null||api.gettype(L,selector)!==5||!viewActive(L,selector,'MapUISelectTroops')))return null;
  const out={goal:readPath(L,['UIObjectManager','MapUISelectTroops','targetPos'],1,{left:8}),
   formGoal:city?fieldValue(L,ui,'DstPos',1):null,
   empty:readPath(L,['UIObjectManager','MapUISelectTroops','isGotoEmptySpace'],0,{left:1}),
   target:readPath(L,['UIObjectManager','MapUISelectTroops','CurTargetId'],0,{left:1}),
   offensive:readPath(L,['UIObjectManager','MapUISelectTroops','isOffensive'],0,{left:1}),picker:null,units:[],selection:{}};
  const prefix=['UIObjectManager','MapUISelectTroops'],popup=['UIObjectManager','TroopSelectedPopUp'];
  const selection=out.selection;
  for(const key of ['selectIndex','isMultiSelectMode'])selection[key]=readPath(L,[...prefix,key],0,{left:1});
  for(const key of ['selectIndex','isMultiSelectMode','ShowPveAPBuy','troopMoveTime'])
   selection['popup_'+key]=readPath(L,[...popup,key],0,{left:1});
  const selected=selection.selectIndex;
  if(Number.isSafeInteger(selected)&&selected>0&&selected<=9){
    selection.row=barbarianTroopIdentity(L,[...prefix,'ListData',selected,'troopInfo']);
   selection.type=readPath(L,[...prefix,'ListData',selected,'type'],0,{left:1});
  }
  const units=city?pushField(L,ui,'AllUnit'):null;
  if(units!==null&&api.gettype(L,units)===5)for(let i=1;i<=64;i++){
   api.rawgeti(L,units,i);const row=api.gettop(L);
   if(api.gettype(L,row)===0)break;
   if(api.gettype(L,row)!==5)return null;
   const unit={index:i};for(const key of ['type','unitId','unitCount'])unit[key]=fieldValue(L,row,key,0);
   unit.bound=api.gettype(L,pushField(L,row,'item'))===7;out.units.push(unit);api.settop(L,row-1);
   if(i===64)return null;
  }
  const picker=rawPath(L,['UIObjectManager','HeroSelectPop']);
  if(city&&picker!==null&&api.gettype(L,picker)===5&&viewActive(L,picker,'HeroSelectPop')){
   const value={};for(const name of ['curSelHeroId','FilterRarity','FilterSpecialized','FilterSpecialties',
        'IsOpenFilterPage','scale','offsetY','isCityWall'])
     value[name]=fieldValue(L,picker,name,0);
   value.slot=readPath(L,['UIObjectManager','HeroSelectPop','setting','tag'],0,{left:1});
   const rows=pushField(L,picker,'herosData');if(api.gettype(L,rows)!==5)return null;
   value.heroes=[];
   for(let i=1;i<=256;i++){
    api.rawgeti(L,rows,i);const row=api.gettop(L);
    if(api.gettype(L,row)===0){out.picker=value;return out;}
    if(api.gettype(L,row)!==5)return null;
    const id=fieldValue(L,row,'Id',0);
    if(!Number.isSafeInteger(id)||id<=0)return null;
    value.heroes.push(id);api.settop(L,row-1);
   }
   return null;
  }
  return out;
 }finally{api.settop(L,base);}
}
function barbarianPveTalent(L,hero){
 const base=api.gettop(L);
 try{
  const page=hero.TalentPage&&hero.TalentPage[String(hero.CurrentPage)],talents=page&&page.TalentMap;
  if(!Number.isSafeInteger(hero.CurrentPage)||!talents||typeof talents!=='object'
      ||Object.entries(talents).some(([key,n])=>!/^\d+$/.test(key)||!Number.isSafeInteger(n)||n<1||n>5))return null;
  const getter=rawPath(L,['HeroHandler','GetTalentConfig']);
  const configs=getter===null?null:capturedData(L,getter,1,1);
  if(configs===null||api.gettype(L,configs.index)!==5)return null;
  const nodeGetter=rawPath(L,['HeroHandler','GetTalentCfgByNodeId']);
  const levels=nodeGetter===null?null:capturedData(L,nodeGetter,1,1);
  if(levels===null||api.gettype(L,levels.index)!==5)return null;
  const nodes={};let cost=0;
  // GetPveCostBuff's installed contract names precisely these two config IDs.
  // Read their captured data, never invoke either Lua getter.
  for(const id of [804,1007]){
   api.rawgeti(L,configs.index,id);const rowIndex=api.gettop(L);
   const config={ID:configScalarField(L,rowIndex,'ID'),Node:configScalarField(L,rowIndex,'Node')};
   if(config.ID!==id||!Number.isSafeInteger(config.Node)||config.Node<=0)return null;
   const level=talents[String(id)]||0;
   nodes[String(id)]={node:config.Node,level};
   if(level){
    api.rawgeti(L,levels.index,config.Node);const list=api.gettop(L);
    if(api.gettype(L,list)!==5)return null;
    api.rawgeti(L,list,level);const row=nativeScalarRow(L,api.gettop(L));
    if(!row||row.ID!==config.Node||row.Lv!==level||!Number.isFinite(row.Param1)||row.Param1<0||row.Param1>50)return null;
    cost+=row.Param1;
   }
  }
  return {cost,nodes};
 }finally{api.settop(L,base);}
}
function barbarianReports(L){
 const base=api.gettop(L);
 try{
  const mails=rawPath(L,['MailData','Datas','Report']);if(mails===null||api.gettype(L,mails)!==5)return null;
  const out={};let scanned=0;api.pushnil(L);
  while(api.next(L,mails)!==0){
   const mail=api.gettop(L);if(++scanned>512)return null;
   if(api.gettype(L,mail)===5&&fieldValue(L,mail,'type',0)==='Battle'){
    const id=fieldValue(L,mail,'id',0),body=pushField(L,mail,'body');
    if(api.gettype(L,body)!==5)return null;
    const content=pushField(L,body,'content');if(api.gettype(L,content)!==5)return null;
    const self=pushField(L,content,'SelfChar');if(api.gettype(L,self)!==5)return null;
    const row={server:fieldValue(L,content,'GsId',0),battle:fieldValue(L,content,'Id',0),
     start:fieldValue(L,content,'Bts',0),end:fieldValue(L,content,'Ets',0),
     omitted:fieldValue(L,content,'DataOmit',0),player:fieldValue(L,self,'PId',0),
     charId:fieldValue(L,self,'CId',0),troopId:fieldValue(L,self,'CtId',0),attacks:{}};
    const attacks=pushField(L,content,'Attacks');if(api.gettype(L,attacks)!==5)return null;
    api.pushnil(L);let count=0;
    while(api.next(L,attacks)!==0){
     const attack=api.gettop(L);if(++count>64||api.gettype(L,attack)!==5)return null;
     const identity=pushField(L,attack,'CIdt');if(api.gettype(L,identity)!==5)return null;
     const enemy=fieldValue(L,identity,'CId',0);
     const result={id:enemy,player:fieldValue(L,identity,'PId',0),type:fieldValue(L,identity,'CT',0),
      npcType:fieldValue(L,identity,'NpcType',0),barbarianType:fieldValue(L,identity,'NpcBType',0)};
     for(const key of ['Kill','Damage']){
      const details=pushField(L,attack,key);if(api.gettype(L,details)!==5)return null;
      result[key]={};for(const field of ['Cnt','Max','Death','BadHurt'])result[key][field]=fieldValue(L,details,field,0);
     }
     row.attacks[String(enemy)]=result;api.settop(L,attack-1);
    }
    if(typeof id!=='string'||Object.prototype.hasOwnProperty.call(out,id))return null;
    out[id]=row;
   }
   api.settop(L,mail-1);
  }
  return out;
 }finally{api.settop(L,base);}
}
function configScalarField(L,row,field){
 const base=api.gettop(L);
 try{
  if(api.gettype(L,row)!==7||api.getmetatable(L,row)===0)return null;
  const getter=pushField(L,api.gettop(L),'__index');if(!dataReader(L,getter))return null;
  api.pushvalue(L,row);const text=Memory.allocUtf8String(field);api.pushlstring(L,text,field.length);
  if(api.pcall(L,2,1,0)!==0||api.gettype(L,-1)!==3)return null;
  return scalar(L,-1);
 }finally{api.settop(L,base);}
}
const barbarianConfigCache=new Map();
function barbarianConfig(L,id){
 const base=api.gettop(L);
 try{
  if(!Number.isSafeInteger(id)||id<=0)return null;
  const configs=rawPath(L,['GameDatas','barbarian_Barbarian']);
  if(configs===null||api.gettype(L,configs)!==7)return null;
  const identity=api.touserdata(L,configs).toString()+':'+id;
  if(barbarianConfigCache.has(identity))return barbarianConfigCache.get(identity);
  if(api.getmetatable(L,configs)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');if(!dataReader(L,pairs))return null;
  api.pushvalue(L,configs);if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;
  if(!dataReader(L,iterator))return null;
  for(let count=0;count<12000;count++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0)return null;
   if(api.gettype(L,-2)===0)return null;
   const candidate=api.gettop(L);
   if(configScalarField(L,candidate,'ID')===id){
    const row=nativeScalarRow(L,candidate);
    if(row&&row.ID===id){barbarianConfigCache.set(identity,row);return row;}
    return null;
   }
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  return null;
 }finally{api.settop(L,base);}
}
function discoveredPlaceTarget(L){
 const base=api.gettop(L);
 try{
  const popup=rawPath(L,['UIObjectManager','MapUnkownCityPopUp']);
  if(popup!==null&&api.gettype(L,popup)===5&&viewActive(L,popup,'MapUnkownCityPopUp')){
   const id=fieldValue(L,popup,'targetId',0);
   return Number.isSafeInteger(id)&&id>0?readPath(L,['MapData','chars',id],3,{left:256}):null;
  }
  const rows=rawPath(L,['UIObjectManager','CityUIScoutsManagement','ListDatas']);
  if(rows===null||api.gettype(L,rows)!==5)return null;
  const cx=readPath(L,['UIObjectManager','MapHudPanel','CurViewX'],0,{left:1});
  const cy=readPath(L,['UIObjectManager','MapHudPanel','CurViewY'],0,{left:1});
  const ox=readPath(L,['FogMgr','m_kingdomOffsetX'],0,{left:1});
  const oy=readPath(L,['FogMgr','m_kingdomOffsetY'],0,{left:1});
  if(![cx,cy,ox,oy].every(v=>typeof v==='number'&&Number.isFinite(v)))return null;
  let kind=null,wanted=null,seen=0;api.pushnil(L);
  while(api.next(L,rows)!==0){
   const candidate=api.gettop(L);if(++seen>2048)return null;
   if(api.gettype(L,candidate)===5){
    const type=fieldValue(L,candidate,'type',0),id=fieldValue(L,candidate,'caviId',0);
    const pos=fieldValue(L,candidate,'pos',1);
    if([10,11].includes(type)&&Number.isSafeInteger(id)&&id>0&&pos
       &&Math.abs(pos.x+ox-cx)<.05&&Math.abs(pos.y+oy-cy)<.05){kind=type;wanted=id;break;}
   }
   api.settop(L,candidate-1);
  }
  if(wanted===null)return null;
  const chars=rawPath(L,['MapData','chars']);
  if(chars===null||api.gettype(L,chars)!==5)return null;
  api.pushnil(L);let scanned=0;
  while(api.next(L,chars)!==0){
   const row=api.gettop(L);if(++scanned>2048)return null;
   if(api.gettype(L,row)===5&&fieldValue(L,row,'charType',0)===kind){
    const details=pushField(L,row,kind===11?'village':'cave');
    if(api.gettype(L,details)===5&&fieldValue(L,details,'caviId',0)===wanted)
     return readTable(L,row,3,{left:256},new Set());
    api.settop(L,details-1);
   }
   api.settop(L,row-1);
  }
  return null;
 }finally{api.settop(L,base);}
}
function tutorialStepConfig(L,config,step){
 const base=api.gettop(L);
 try{
  if(api.gettype(L,config)!==7||!Number.isSafeInteger(step)||step<1||step>512)return null;
  const identity=api.touserdata(L,config).toString()+':'+step;
  if(tutorialConfigCache.has(identity))return tutorialConfigCache.get(identity);
  if(api.getmetatable(L,config)===0)return null;
  const getter=pushField(L,api.gettop(L),'__index');
  if(!dataReader(L,getter))return null;
  api.pushvalue(L,config);api.pushnumber(L,step);
  if(api.pcall(L,2,1,0)!==0)return null;
  const row=api.gettop(L);
  const out=nativeScalarRow(L,row);
  if(out!==null)tutorialConfigCache.set(identity,out);
  return out;
 }finally{api.settop(L,base);}
}
function nativeScalarRow(L,row){
 const base=api.gettop(L);
 try{
  if(api.gettype(L,row)!==7||api.getmetatable(L,row)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');
  if(!dataReader(L,pairs))return null;
  api.pushvalue(L,row);if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;
  if(!dataReader(L,iterator))return null;
  const out={};
  for(let n=0;n<80;n++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0)return null;
   if(api.gettype(L,-2)===0)return out;
   const name=scalar(L,-2),type=api.gettype(L,-1);
   if(!['string','number'].includes(typeof name))return null;
   if(typeof name==='string'){
    if(![0,1,3,4].includes(type))return null;
    if(name!=='__proto__')out[name]=scalar(L,-1);
   }
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  return null;
 }finally{api.settop(L,base);}
}
function cachedRewardRows(L,id){
 const base=api.gettop(L);
 try{
  const fn=rawPath(L,['RewardHandler','GetRewardInfo']);
  const capture=fn===null?null:capturedData(L,fn,1,1);
  if(capture===null||api.gettype(L,capture.index)!==5)return null;
  api.rawgeti(L,capture.index,id);const rows=api.gettop(L),out={};
  if(api.gettype(L,rows)!==5)return null;
  for(let i=1;i<=16;i++){
   api.rawgeti(L,rows,i);const row=api.gettop(L);
   if(api.gettype(L,row)===0)return out;
   const loot=nativeScalarRow(L,row);if(loot===null)return null;
   out[String(i)]=loot;api.settop(L,row-1);
  }
  return null;
 }finally{api.settop(L,base);}
}
function onboardingBattle(L){
 const base=api.gettop(L),out={};
 try{
  out.config=readPath(L,['ScenarioMgr','currentCfgId'],0,{left:1});
  out.state=readPath(L,['ScenarioData','ScenarioState'],0,{left:1});
  out.victoryConfig=readPath(L,['UIObjectManager','CanyonLevelVictoryPage','m_resultContent','Info','CfgID'],0,{left:1});
  out.rewardDone=readPath(L,['UIObjectManager','CanyonLevelVictoryPage','rewardShowEnd'],0,{left:1});
  for(const [key,name,depth] of [['phase','m_firstPlayTutStep',0],['mode','m_curShowMode',0],
    ['selected','m_selectedHero',1],['skill','m_waitCanUseSkill',1],['auto','m_needInstructAutoSkill',0],
    ['speed','m_needInstructSpeedUp',0],['skillClicks','m_clickUseSkillTimers',1]])
   out[key]=readPath(L,['UIObjectManager','CanyonLevelHUD',name],depth,{left:64});
  out.guide={};
  for(const [key,name,depth] of [['force','forceClick',0],['callback','needClickCb',0],['is3D','is3D',0],['position','m_worldPos',1]])
   out.guide[key]=readPath(L,['UIObjectManager','QuestGuide',name],depth,{left:16});
  return out;
 }finally{api.settop(L,base);}
}
function tutorialState(L){
 const base=api.gettop(L),out={ready:false};
 try{
  const data=rawPath(L,['TutorialData']);if(data===null||api.gettype(L,data)!==5)return out;
  out.name=fieldValue(L,data,'CurConfigName',0);out.type=fieldValue(L,data,'CurTutorialType',0);
  out.step=fieldValue(L,data,'CurStep',0);
  if(out.name==='first_enter_vippage'){
   out.vip={};
   for(const key of ['VipExp','VipLevel','ContinuousLogin','CanGetFreePoint','CanGetFreeBox'])
    out.vip[key]=readPath(L,['VipData',key],0,{left:1});
   const points=rawPath(L,['GameDatas','vip_VIP_point']);
   out.vip.pointConfig=points===null?null:tutorialStepConfig(L,points,1);
   out.vip.freeLoot=cachedRewardRows(L,9001);
  }
  out.saved=fieldValue(L,data,'CurSavedStepData',1);
  if(out.name==='slg_2_v4'&&out.type==='FTE'&&out.step===101&&out.saved
     &&out.saved.tutorialVersion==='slg_2_v4'&&out.saved.justFinishStepIndex===100&&out.saved.finishTutorial===true){
   out.ready=true;out.active=false;out.completed=true;return out;
  }
  out.enterTime=readPath(L,['TutorialMgr','curStepEnterTimeMs'],0,{left:1});
  if(out.name===null&&out.type===null){out.ready=true;out.active=false;return out;}
  const config=pushField(L,data,'CurConfig');
  out.config=tutorialStepConfig(L,config,out.step);
  if(out.name==='slg_2_new_event')out.signup=signupState(L);
  if(out.name==='unlock_radar'){
   out.radar=readPath(L,['TutorialData','ExtData'],2,{left:128});
   out.radarPopupTarget=readPath(L,['UIObjectManager','MapUIBarbarianPopUp','TargetId'],0,{left:1});
   out.radarTasks=readPath(L,['RadarTaskData','MiniTaskInfo'],2,{left:128});
   out.radarShown=readPath(L,['UIObjectManager','RadarTaskMainPage','showTaskIDs'],1,{left:32});
   out.radarLoot=cachedRewardRows(L,49101);
   out.radarRewardTask=readPath(L,['UIObjectManager','RadarTaskMainPageReward','radarTaskId'],0,{left:1});
   out.radarSelectTarget=readPath(L,['UIObjectManager','MapUISelectTroops','CurTargetId'],0,{left:1});
   out.radarVillageTarget=readPath(L,['UIObjectManager','MapUnkownCityPopUp','targetId'],0,{left:1});
   out.radarVillageCave=readPath(L,['UIObjectManager','MapUnkownCityPopUp','m_caviId'],0,{left:1});
   const form=rawPath(L,['UIObjectManager','SendTroopsMain']);
   if(form!==null&&api.gettype(L,form)===5){
    out.radarForm={};
    for(const key of ['DstCharId','SrcCharId','CharType','CollectResType','SelHeroIds','SelectUnits','TotalNum',
      'isAttackNpc','isAggressive','Dispatched','troopType','troopMoveTime'])
     out.radarForm[key]=fieldValue(L,form,key,['SelHeroIds','SelectUnits'].includes(key)?1:0);
   }
   if(Number.isSafeInteger(out.radarPopupTarget)&&out.radarPopupTarget>0){
    out.radarEnemy=readPath(L,['MapData','chars',out.radarPopupTarget,'npcInfo'],2,{left:64});
    out.radarEnemyOwner=readPath(L,['WorldMgr','allObjs',out.radarPopupTarget,'playerId'],0,{left:1});
   }
  }
   if(out.config===null){
    if(out.name===''&&out.type===''&&out.step===0&&api.gettype(L,config)===0){
     out.ready=true;out.active=false;return out;
    }
   if(out.name==='first_enter_vippage'&&out.type==='TRIGGERED'&&out.step===8&&api.gettype(L,config)===0
      &&readPath(L,['TutorialData','TriggerTutorialState','first_enter_vippage'],0,{left:1})===true){
    out.ready=true;out.active=false;out.completed=true;
   }
   const ended={trigger_towncenter_2_3:[4,5],slg_2_towncenter_3:[23,24,25],slg_2_towncenter_enter_bronze:[3],
    first_enter_itembox:[3,4],slg_2_towncenter_5_1:[15,16],slg_2_new_event:[5,6],unlock_radar:[42,43,44],
     Unlock_hero_level_up:[2,3],first_select_campus:[4,5],first_enter_technology:[3,4],slg_2_recycle_plants:[4,5]};
   if(out.type==='TRIGGERED'&&Object.prototype.hasOwnProperty.call(ended,out.name)
      &&ended[out.name].includes(out.step)&&api.gettype(L,config)===0
      &&readPath(L,['TutorialData','TriggerTutorialState',out.name],0,{left:1})===true){
    out.ready=true;out.active=false;out.completed=true;
   }
   return out;
  }
  const dialog=rawPath(L,['UIObjectManager','Dialog']);
  out.dialogVisible=dialog!==null&&api.gettype(L,dialog)===5&&viewActive(L,dialog,'Dialog');
  if(out.dialogVisible){
   out.dialog=fieldValue(L,dialog,'DialogConfig',1);
   out.dialogClosing=fieldValue(L,dialog,'m_needCloseUI',0);
  }
  const cover=rawPath(L,['UIObjectManager','FTECover']);
  out.coverVisible=cover!==null&&api.gettype(L,cover)===5&&viewActive(L,cover,'FTECover');
  if(out.coverVisible)out.cover=fieldValue(L,cover,'FTEConverConfig',1);
  out.followPos=readPath(L,['UIObjectManager','FTECover','FTEConverConfig','CoverTransform','worldPos'],1,{left:8});
  if(out.name==='slg_2_recycle_plants'&&cover!==null&&api.gettype(L,cover)===5){
   const config=pushField(L,cover,'FTEConverConfig');
   if(api.gettype(L,config)===5){
    out.cover={};for(const key of ['Target','CoverName','EndCondition','DelayTime'])out.cover[key]=fieldValue(L,config,key,0);
    let plant=pushField(L,config,'BuildObj');
    if(api.gettype(L,plant)!==5)plant=rawPath(L,['CityManager','SelectedObj']);
    if(plant!==null&&api.gettype(L,plant)===5){
     out.plant={};for(const key of ['id','type','lv','state','width','length'])out.plant[key]=fieldValue(L,plant,key,0);
    }
   }
  }
   Object.assign(out,buildingPreview(L));
  const upgrade=rawPath(L,['UIObjectManager','UpgradeBuilding']);
  out.upgradeVisible=upgrade!==null&&api.gettype(L,upgrade)===5&&viewActive(L,upgrade,'UpgradeBuilding');
  if(out.upgradeVisible){
   out.upgrade={};
   for(const [key,name,depth] of [['id','buildingId',0],['type','btype',0],['level','curLv',0],['can','canUpgrade',0],
      ['item','itemType',0],['items','itemNum',0],['cost','requireRss',2]])out.upgrade[key]=fieldValue(L,upgrade,name,depth);
  }
  const guide=rawPath(L,['UIObjectManager','QuestGuide']);
  out.guideVisible=guide!==null&&api.gettype(L,guide)===5&&viewActive(L,guide,'QuestGuide');
  if(out.guideVisible){
   out.guide={};
   for(const key of ['forceClick','needClickCb','is3D'])out.guide[key]=fieldValue(L,guide,key,0);
   out.guide.worldPos=fieldValue(L,guide,'m_worldPos',1);
  }
  out.chapter=readPath(L,['ChapterQuestData','CurrentChapterId'],0,{left:1});
  out.chapterQuests=readPath(L,['ChapterQuestData','QuestInfos'],2,{left:256});
  if(out.step===76&&out.chapter===1){
   const fn=rawPath(L,['RewardHandler','GetRewardInfo']);
   const capture=fn===null?null:capturedData(L,fn,1,1);
   if(capture!==null&&api.gettype(L,capture.index)===5){
    api.rawgeti(L,capture.index,23330016);const rows=api.gettop(L);
    if(api.gettype(L,rows)===5){
     out.chapterLoot={};
     for(let i=1;i<=8;i++){
      api.rawgeti(L,rows,i);const row=api.gettop(L);
      if(api.gettype(L,row)===0){api.settop(L,row-1);break;}
      const loot=nativeScalarRow(L,row);
      if(loot===null){out.chapterLoot=null;break;}
      out.chapterLoot[String(i)]=loot;api.settop(L,row-1);
      if(i===8)out.chapterLoot=null;
     }
    }
   }
  }
  const story=rawPath(L,['UIObjectManager','StoryConversation']);
  if(out.name==='slg_2_towncenter_5_1'){
   out.fred={loot:cachedRewardRows(L,23330011)};
   const panel=rawPath(L,['UIObjectManager','AidFredPopup']);
   if(panel!==null&&api.gettype(L,panel)===5){
    out.fred.chapter=fieldValue(L,panel,'m_chapterId',0);
    out.fred.dialogSkip=fieldValue(L,panel,'m_dialogSkip',0);
    const quests=pushField(L,panel,'m_questList');
    if(api.gettype(L,quests)===5){api.rawgeti(L,quests,1);out.fred.firstQuest=nativeScalarRow(L,api.gettop(L));}
   }
  }
  out.storyVisible=story!==null&&api.gettype(L,story)===5&&viewActive(L,story,'StoryConversation');
  if(out.storyVisible){
   out.story={};
   for(const [key,name,depth] of [['id','curStoryId',0],['canClick','isCanClick',0],['choiceShown','m_choiceOptionShown',0],
     ['return','returnType',0],['end','isPlayEnd',0]])out.story[key]=fieldValue(L,story,name,depth);
   const node=pushField(L,story,'curNode');
   out.story.node=api.gettype(L,node)===5?readTable(L,node,1,{left:128},new Set()):null;
   const graph=pushField(L,story,'curStoryConfig');
   out.story.graph=api.gettype(L,graph)===5?readTable(L,graph,2,{left:2048},new Set()):null;
   const writer=pushField(L,story,'typeWritter');
   if(api.gettype(L,writer)===5)out.story.typing=fieldValue(L,writer,'isValid',0);
  }
  const unlock=rawPath(L,['UIObjectManager','NewFeaturesUnlockedPage']);
  out.unlockVisible=unlock!==null&&api.gettype(L,unlock)===5&&viewActive(L,unlock,'NewFeaturesUnlockedPage');
  if(out.unlockVisible){
   out.unlock={canClick:fieldValue(L,unlock,'canClick',0),clicked:fieldValue(L,unlock,'hasClick',0),
    items:fieldValue(L,unlock,'unlockItems',2)};
  }
  const tavern=rawPath(L,['UIObjectManager','TavernPage']);
  out.tavernVisible=tavern!==null&&api.gettype(L,tavern)===5&&viewActive(L,tavern,'TavernPage');
  if(out.tavernVisible){
   out.tavern={menu:fieldValue(L,tavern,'curMenu',0),multi:fieldValue(L,tavern,'MulitMode',0),mode:fieldValue(L,tavern,'mode',0)};
   out.tavern.items=readPath(L,['UIObjectManager','TavernPage','gainItems'],2,{left:128});
  }
  const hero=rawPath(L,['UIObjectManager','AllUIHeroCheckIn_SLG']);
  out.heroVisible=hero!==null&&api.gettype(L,hero)===5&&viewActive(L,hero,'AllUIHeroCheckIn_SLG');
  if(out.heroVisible){
   out.hero={id:fieldValue(L,hero,'ShowHeroId',0),star:fieldValue(L,hero,'ShowHeroStar',0)};
   out.heroTokens={};
   if(out.tavern&&out.tavern.items)for(const row of Object.values(out.tavern.items)){
    if(row&&Number.isSafeInteger(row.Id)){
     const configs=rawPath(L,['ItemData','ItemConfigs']);
     if(configs!==null&&api.gettype(L,configs)===5){
      api.rawgeti(L,configs,row.Id);const item=nativeScalarRow(L,api.gettop(L));
      if(item&&item.OpType===5&&item.SubType===5&&item.LC_T===('LC_HERO_NAME_'+out.hero.id))
       out.heroTokens[String(row.Id)]=out.hero.id;
     }
    }
   }
   const owned=rawPath(L,['HeroHandler','HeroMap']);
   if(owned!==null&&api.gettype(L,owned)===5&&Number.isSafeInteger(out.hero.id)){
    api.rawgeti(L,owned,out.hero.id);const row=api.gettop(L);
    if(api.gettype(L,row)===5)out.hero.owned={id:fieldValue(L,row,'Id',0),star:fieldValue(L,row,'Star',0),
     created:fieldValue(L,row,'CreateTime',0),level:fieldValue(L,row,'Level',0)};
   }
  }
  if(out.name==='slg_2_towncenter_3'){
   out.gift={rewardId:23330001,loot:cachedRewardRows(L,23330001)};
   const reward=rawPath(L,['UIObjectManager','RoutineRewardsCollect']);
   if(reward!==null&&api.gettype(L,reward)===5&&viewActive(L,reward,'RoutineRewardsCollect')){
    out.gift.popup={showing:fieldValue(L,reward,'isShowing',0),flew:fieldValue(L,reward,'m_itemFlew',0),rows:{}};
    const items=pushField(L,reward,'rewards');
    if(api.gettype(L,items)===5){
     for(let i=1;i<=4;i++){
      api.rawgeti(L,items,i);const row=api.gettop(L);
      if(api.gettype(L,row)===0)break;
      out.gift.popup.rows[String(i)]=nativeScalarRow(L,row);api.settop(L,row-1);
     }
    }
   }
   const all=rawPath(L,['CityManager','AllObjs']);
   if(all!==null&&api.gettype(L,all)===5){
    api.pushnil(L);let count=0;
    while(api.next(L,all)!==0){
     const b=api.gettop(L);
     if(++count>128)break;
     if(api.gettype(L,b)===5&&fieldValue(L,b,'type',0)===1){
      const owner=pushField(L,b,'cityObj'),mgr=pushField(L,owner,'cityheroMgr');
      if(api.gettype(L,mgr)===5){
       out.gift.claiming=fieldValue(L,mgr,'giftRewardClaiming',0);
       const bubble=pushField(L,mgr,'giftBubbleObj');out.gift.bubble=api.gettype(L,bubble)!==0;
       const team=pushField(L,mgr,'giftVillageTeam');
       out.gift.arrived=api.gettype(L,team)===5?fieldValue(L,team,'hasArrived',0):null;
      }
     }
     api.settop(L,b-1);
    }
   }
   out.rescue={};
   out.rescue.id=readPath(L,['TutorialData','ExtData','Fight2_BarbarianCharID'],0,{left:1});
   out.rescue.fight=readPath(L,['TutorialFightData','curFightId'],0,{left:1});
   out.rescue.tick=readPath(L,['TutorialFightData','curFightTickIdx'],0,{left:1});
   out.rescue.popupTarget=readPath(L,['UIObjectManager','MapUIBarbarianPopUp','TargetId'],0,{left:1});
   out.rescue.selectTarget=readPath(L,['UIObjectManager','MapUISelectTroops','CurTargetId'],0,{left:1});
   const heroes=rawPath(L,['UIObjectManager','HeroSelectPop','herosData']);
   if(heroes!==null&&api.gettype(L,heroes)===5){
    out.rescue.heroes={};api.pushnil(L);let scanned=0;
    while(api.next(L,heroes)!==0){
     const row=api.gettop(L),key=scalar(L,-2);
     if(++scanned>80||api.gettype(L,row)!==5){out.rescue.heroes=null;break;}
     out.rescue.heroes[String(key)]={id:fieldValue(L,row,'Id',0),level:fieldValue(L,row,'Level',0),state:fieldValue(L,row,'State',0)};
     api.settop(L,row-1);
    }
   }
   const send=rawPath(L,['UIObjectManager','SendTroopsMain']);
   if(send!==null&&api.gettype(L,send)===5){
    out.rescue.form={};
    for(const key of ['DstCharId','SrcCharId','CharType','CollectResType','SelHeroIds','SelectUnits','TotalNum',
      'isAttackNpc','isAggressive','Dispatched','troopType','troopMoveTime'])
     out.rescue.form[key]=fieldValue(L,send,key,['SelHeroIds','SelectUnits'].includes(key)?1:0);
   }
   const chars=rawPath(L,['MapData','chars']);
   if(chars!==null&&api.gettype(L,chars)===5&&Number.isSafeInteger(out.rescue.id)&&out.rescue.id>0&&out.rescue.id<=2147483647){
    api.rawgeti(L,chars,out.rescue.id);const enemy=api.gettop(L);
    if(api.gettype(L,enemy)===5)for(const [key,name,depth] of [['player','playerId',0],['kind','charType',0],
      ['position','pos',1],['npc','npcInfo',1]])out.rescue[key]=fieldValue(L,enemy,name,depth);
   }
  }
  out.active=true;out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function passMissionConfig(L,kind,id){
 const base=api.gettop(L);
 try{
  const fn=rawPath(L,['BattlePassHandler','GetMissionCfg']);
  if(fn===null)return null;
  const capture=capturedData(L,fn,kind===2?2:3,3);
  if(capture===null||api.gettype(L,capture.index)!==5)return null;
  api.rawgeti(L,capture.index,id);const row=api.gettop(L);
  if(api.gettype(L,row)!==7)return null;
  const object=api.touserdata(L,row);
  if(object.isNull())return null;
  const identity=object.readPointer().toString()+':'+kind+':'+id;
  if(passConfigCache.has(identity))return passConfigCache.get(identity);
  if(api.getmetatable(L,row)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');
  if(!dataReader(L,pairs))return null;
  api.pushvalue(L,row);if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;
  if(!dataReader(L,iterator))return null;
  const out={};
  for(let n=0;n<128;n++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0)return null;
   if(api.gettype(L,-2)===0){passConfigCache.set(identity,out);return out;}
   const name=scalar(L,-2);if(['ID','Id','Score','Require'].includes(name))out[name]=scalar(L,-1);
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  return null;
 }finally{api.settop(L,base);}
}
function lucerneState(L){
 const base=api.gettop(L),out={ready:false,visible:false};
 try{
  const data=rawPath(L,['BattlePassData']);if(data===null||api.gettype(L,data)!==5)return out;
  for(const [key,name,depth] of [['time','m_TimeInfo',1],['level','m_LevelInfo',1],['pay','m_nPayType',0],
    ['daily','m_nDailyStatus',0]])out[key]=fieldValue(L,data,name,depth);
  const constants=rawPath(L,['BattlePassHandler','GetConstCfg']);
  const cfg=constants===null?null:capturedData(L,constants,1,1);
  if(cfg===null)return out;
  out.levelExp=fieldValue(L,cfg.index,'Lv_experience',0);out.dailyExp=fieldValue(L,cfg.index,'Daily_experience',0);
  out.extraExp=fieldValue(L,cfg.index,'Extra_add_exp',0);out.weeks={};
  function missions(index,kind){
   if(api.gettype(L,index)!==5)return null;
   const rows={};let count=0;api.pushnil(L);
   while(api.next(L,index)!==0){
    if(++count>32||api.gettype(L,-1)!==5)return null;
    const key=scalar(L,-2),row=api.gettop(L),id=fieldValue(L,row,'TaskID',0);
    if(!Number.isSafeInteger(id)||id<=0)return null;
    const config=passMissionConfig(L,kind,id);
    if(config===null)return null;
    rows[String(key)]={id,status:fieldValue(L,row,'TaskStatus',0),score:config.Score,
     group:kind===1?fieldValue(L,row,'GroupID',0):null,extra:kind===1?fieldValue(L,row,'AddtionExp',0):false};
    api.settop(L,api.gettop(L)-1);
   }
   return rows;
  }
  let index=pushField(L,data,'m_aaMissionWeek');if(api.gettype(L,index)!==5)return out;
  api.pushnil(L);let weeks=0;
  while(api.next(L,index)!==0){
   if(++weeks>8)return out;
   const key=scalar(L,-2),rows=missions(api.gettop(L),1);if(rows===null)return out;
   out.weeks[String(key)]=rows;api.settop(L,api.gettop(L)-1);
  }
  out.season=missions(pushField(L,data,'m_aMisionSeason'),2);if(out.season===null)return out;
  index=pushField(L,data,'m_aRewardStatus');if(api.gettype(L,index)!==5)return out;
  out.rewards={};api.pushnil(L);let count=0;
  while(api.next(L,index)!==0){
   if(++count>100||api.gettype(L,-1)!==5)return out;
   const row=api.gettop(L),key=scalar(L,-2);
   out.rewards[String(key)]={level:fieldValue(L,row,'Level',0),free:fieldValue(L,row,'FreeGet',0),
    paid:fieldValue(L,row,'PayGet',0),loot:fieldValue(L,row,'FreeLoot',1)};
   api.settop(L,api.gettop(L)-1);
  }
  const ui=rawPath(L,['UIObjectManager','BattlePassMain']);
  if(ui!==null&&api.gettype(L,ui)===5&&viewActive(L,ui,'BattlePassMain')){
   out.visible=true;
   const top=capturedData(L,pushField(L,ui,'SwitchTapTop'),1,6);
   const mission=capturedData(L,pushField(L,ui,'SwitchTapMission'),1,4);
   const week=capturedData(L,pushField(L,ui,'SwitchTapWeek'),1,1);
   if(top===null||mission===null||week===null)return out;
   out.tab=scalar(L,top.index);out.missionTab=scalar(L,mission.index);out.week=scalar(L,week.index);
   out.newSeason=fieldValue(L,ui,'isShowNewSeason',0);
  }
  const reward=rawPath(L,['UIObjectManager','battlePassPopWindow_Reward']);
  out.rewardVisible=reward!==null&&api.gettype(L,reward)===5&&viewActive(L,reward,'battlePassPopWindow_Reward');
  if(out.rewardVisible){
   const captured=capturedData(L,pushField(L,reward,'OnItemEnter'),2,2);
   if(captured===null||api.gettype(L,captured.index)!==5)return out;
   out.rewardRows=readTable(L,captured.index,2,{left:512},new Set());
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function queuePanel(L){
 const base=api.gettop(L);
 try{
  const target=rawPath(L,['UIObjectManager','MapHudPanel','QueueMgmtList_Leftcontent']);
  if(target===null||api.gettype(L,target)!==7)return {known:false,visible:null};
  const object=api.touserdata(L,target);
  if(object.isNull()||api.getmetatable(L,target)===0)return {known:false,visible:null};
  const meta=api.gettop(L);
  if(fieldValue(L,meta,'__typename',0)!=='GameObject')return {known:false,visible:null};
  const id=object.readU32();
  if(!id||id>0x7fffffff)return {known:false,visible:null};
  const identity=object.toString()+':'+id;
  if(queueActivityObject!==identity){queueActivityObject=identity;queueActivity=null;}
  const descriptor=pushField(L,meta,'activeInHierarchy');
  if(api.gettype(L,descriptor)!==5)return {known:false,visible:null};
  api.rawgeti(L,descriptor,1);
  const getterIndex=api.gettop(L);
  if(api.iscfunction(L,getterIndex)===0)return {known:false,visible:null};
  const getter=api.tocfunction(L,getterIndex);
  const module=Process.findModuleByAddress(getter);
  if(module===null||module.name!=='libil2cpp.so')return {known:false,visible:null};
  const key=getter.toString();
  let watch=activityGetters.get(key);
  if(watch===undefined){
   watch={identity,id};activityGetters.set(key,watch);
   // Observe the getter already called by the game's queue refresh. Never call it ourselves.
   watch.listener=Interceptor.attach(getter,{
    onEnter(args){
     const state=args[0];
     if(api.gettop(state)<1||api.gettype(state,1)!==7)return;
     const userdata=api.touserdata(state,1);
     if(userdata.isNull()||userdata.readU32()!==watch.id||userdata.toString()+':'+watch.id!==watch.identity)return;
     this.state=state;this.identity=watch.identity;
    },
    onLeave(){
     if(this.state&&this.identity===queueActivityObject&&api.gettype(this.state,-1)===1)
      queueActivity={identity:this.identity,visible:api.toboolean(this.state,-1)!==0,time:Date.now()};
    }
   });
  }else{watch.identity=identity;watch.id=id;}
  const age=queueActivity===null?null:Date.now()-queueActivity.time;
  const known=queueActivity!==null&&queueActivity.identity===identity&&age>=0&&age<=1500;
  return {known,visible:known?queueActivity.visible:null,ageMs:age};
 }finally{api.settop(L,base);}
}
function missionTipsIdle(L,index){
 const top=api.gettop(L);
 try{
  // This always-loaded container retains its Unity object after the two tips finish.
  // Only the observed idle state is excluded; missing or active states remain blocking.
  if(fieldValue(L,index,'m_alwaysload',0)!==true||fieldValue(L,index,'TipsState_IDLE',0)!==1)return false;
  const items=pushField(L,index,'TipsItems');
  if(api.gettype(L,items)!==5)return false;
  for(let slot=1;slot<=2;slot++){
   api.rawgeti(L,items,slot);const tip=api.gettop(L);
   if(api.gettype(L,tip)!==5||fieldValue(L,tip,'State',0)!==1)return false;
   api.settop(L,items);
  }
  return true;
 }finally{api.settop(L,top);}
}
function buildingPreview(L){
 const base=api.gettop(L),out={selection:null};
 try{
  const object=rawPath(L,['CityManager','SelectedObj']);
  out.selection=object!==null&&api.gettype(L,object)===5?fieldValue(L,object,'id',0):null;
  const preview=out.selection==='localNewBuilding'?rawPath(L,['CityManager','AllObjs','localNewBuilding']):null;
  if(preview!==null&&api.gettype(L,preview)===5){
   out.preview={};
   for(const key of ['id','type','lv','state','newPosValid','isSelected'])out.preview[key]=fieldValue(L,preview,key,0);
   out.preview.position=fieldValue(L,preview,'position',1);
   const owner=pushField(L,preview,'cityObj');if(api.gettype(L,owner)===5)out.cityOrigin=fieldValue(L,owner,'pos',1);
   const costs=rawPath(L,['CityBuildHandler','BuildingTypeLevelKV']);out.buildCost=null;
   if(costs!==null&&api.gettype(L,costs)===5&&Number.isSafeInteger(out.preview.type)){
    api.rawgeti(L,costs,out.preview.type*100+1);out.buildCost=nativeScalarRow(L,api.gettop(L));
   }
  }
  return out;
 }finally{api.settop(L,base);}
}
function constructionPlan(L){
 const base=api.gettop(L),out={ready:false,groups:{},first:{},limits:{}};
 try{
  function config(index){
   if(api.gettype(L,index)!==7)return null;
   const key=api.touserdata(L,index).toString();
   if(!constructionConfigCache.has(key))constructionConfigCache.set(key,nativeScalarRow(L,index));
   return constructionConfigCache.get(key);
  }
  const list=rawPath(L,['CityBuildData','NewBuildingList']);
  const costs=rawPath(L,['CityBuildHandler','BuildingTypeLevelKV']);
  const limits=rawPath(L,['CityBuildHandler','BuildingCountLimitMap']);
  if(list===null||costs===null||limits===null||[list,costs,limits].some(i=>api.gettype(L,i)!==5))return out;
  for(let group=1;group<=3;group++){
   api.rawgeti(L,list,group);const rows=api.gettop(L);if(api.gettype(L,rows)!==5)return out;
   out.groups[String(group)]={};api.pushnil(L);let scanned=0;
   while(api.next(L,rows)!==0){
    if(++scanned>128)return out;
    const key=scalar(L,-2),row=config(api.gettop(L));
    if(row===null||!Number.isSafeInteger(key))return out;
    out.groups[String(group)][String(key)]=row;api.settop(L,api.gettop(L)-1);
   }
   api.settop(L,rows-1);
  }
   for(const type of [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,28,30,31]){
   api.rawgeti(L,costs,type*100+1);let row=api.gettop(L);
   if(api.gettype(L,row)===7)out.first[String(type)]=config(row);
   api.settop(L,row-1);api.rawgeti(L,limits,type);row=api.gettop(L);
   if(api.gettype(L,row)===7)out.limits[String(type)]=config(row);
   api.settop(L,row-1);
  }
  out.sizes=readPath(L,['CityBuildHandler','BuildingTypeSizeKV'],1,{left:1024});
  const panel=rawPath(L,['UIObjectManager','BuildNewBuilding']);out.ui={visible:false};
  if(panel!==null&&api.gettype(L,panel)===5&&viewActive(L,panel,'BuildNewBuilding')){
   out.ui={visible:true,group:fieldValue(L,panel,'curClass',0),itemHeight:fieldValue(L,panel,'itemHeight',0),rows:{}};
   const rows=pushField(L,panel,'dataList');if(api.gettype(L,rows)!==5)return out;
   api.pushnil(L);let count=0;
   while(api.next(L,rows)!==0){
    if(++count>128)return out;
    const key=scalar(L,-2),row=config(api.gettop(L));
    if(!Number.isSafeInteger(key)||row===null)return out;
    out.ui.rows[String(key)]={type:row.Type,id:row.ID};api.settop(L,api.gettop(L)-1);
   }
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function vipConfig(L){
 const base=api.gettop(L),out={ready:false};
 try{
  out.level=readPath(L,['VipData','VipLevel'],0,{left:1});
  out.schema=readPath(L,['UserData','Schema'],0,{left:1});
  const getter=rawPath(L,['VipHandler','GetVipConfigBySchema']);
  const capture=getter===null?null:capturedData(L,getter,1,1),cache=capture===null?null:capture.index;
  if(cache===null||api.gettype(L,cache)!==5||!Number.isSafeInteger(out.level)||out.level<0)return out;
  out.rows={};api.pushnil(L);let count=0;
  while(api.next(L,cache)!==0){
   if(++count>16)return out;
   const key=scalar(L,-2),levels=api.gettop(L);
   if(Number.isSafeInteger(key)&&api.gettype(L,levels)===5){
    api.rawgeti(L,levels,out.level);const row=api.gettop(L);
    out.rows[String(key)]=nativeScalarRow(L,row);api.settop(L,row-1);
   }
   api.settop(L,levels-1);
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function sideQuests(L){
 const base=api.gettop(L),out={ready:false,rows:{},statuses:{},visible:false,entryY:155};
 try{
  const quests=rawPath(L,['QuestData','NormalQuests']);if(quests===null||api.gettype(L,quests)!==5)return out;
  const ids=[],seen=new Set();api.pushnil(L);let scanned=0;
  while(api.next(L,quests)!==0){
   const row=api.gettop(L);if(++scanned>4096||api.gettype(L,row)!==5)return out;
   const id=fieldValue(L,row,'Id',0),status=fieldValue(L,row,'Stat',0);
   if(!Number.isSafeInteger(id)||id<1||!Number.isSafeInteger(status)||seen.has(id))return out;
   seen.add(id);if(status===2){out.statuses[String(id)]=status;ids.push(id);}api.settop(L,row-1);
  }
  out.available=ids.length;out.completed=readPath(L,['QuestData','MainCompleted'],0,{left:1});
  const panel=rawPath(L,['UIObjectManager','QuestSystemMainPage']);
  if(panel!==null&&api.gettype(L,panel)===5){
   out.visible=viewActive(L,panel,'QuestSystemMainPage');out.tab=fieldValue(L,panel,'curSelPanelType',0);
   if(out.visible&&out.tab===1)out.display=readPath(L,['UIObjectManager','QuestSystemMainPage','mainDataSource'],3,{left:1024});
  }
  const saved=readPath(L,['TutorialData','CurSavedStepData'],1,{left:16});
  if(saved&&saved.tutorialVersion==='slg_2_v4'){
   out.entryY=null;
   if(readPath(L,['ChapterQuestData','CurrentChapterId'],0,{left:1})===2
      &&readPath(L,['ChapterQuestData','QuestInfos',10,'Status'],0,{left:1})===3)out.entryY=178;
  }
  if(ids.length>32)return out;
  if(ids.length){
   const fn=rawPath(L,['QuestHandler','GetNormalQuestConfig']),capture=fn===null?null:capturedData(L,fn,1,1);
   if(capture===null||api.gettype(L,capture.index)!==5)return out;
   const schema=readPath(L,['QuestData','StrategicSchema'],0,{left:1});if(!Number.isSafeInteger(schema))return out;
   api.rawgeti(L,capture.index,schema);const configs=api.gettop(L);if(api.gettype(L,configs)!==5)return out;
   for(const id of ids){
    api.rawgeti(L,configs,id);const row=api.gettop(L),cfg=nativeScalarRow(L,row);
    if(cfg===null||cfg.ID!==id||!Number.isSafeInteger(cfg.RewardID))return out;
    out.rows[String(id)]={config:cfg,loot:cachedRewardRows(L,cfg.RewardID)};api.settop(L,row-1);
   }
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function researchForm(L){
 const base=api.gettop(L),out={visible:false};
 try{
  const panel=rawPath(L,['UIObjectManager','ResearchRequestPage2']);
  if(panel===null||api.gettype(L,panel)!==5||!viewActive(L,panel,'ResearchRequestPage2'))return out;
  out.visible=true;
  const data=pushField(L,panel,'Datas');
  if(api.gettype(L,data)===5){
   out.type=fieldValue(L,data,'TypeID',0);out.current=fieldValue(L,data,'curlevel',0);
   out.max=fieldValue(L,data,'maxlevel',0);
   out.level=Number.isSafeInteger(out.current)?out.current+1:null;
   const cfg=pushField(L,data,'nextlevelInfo');out.config=nativeScalarRow(L,cfg);
  }
  const costs=readPath(L,['UIObjectManager','ResearchRequestPage2','RssRequire'],1,{left:64});out.cost=null;
  if(costs&&typeof costs==='object'&&!costs.$truncated){
   const parsed={};let valid=true;
   for(const row of Object.values(costs)){
    if(!row||!Number.isSafeInteger(row.res_type)||row.res_type<1||row.res_type>4
       ||!Number.isSafeInteger(row.res_num)||row.res_num<=0||Object.prototype.hasOwnProperty.call(parsed,row.res_type)){valid=false;break;}
    parsed[String(row.res_type)]=row.res_num;
   }
   if(valid)out.cost=parsed;
  }
  return out;
 }finally{api.settop(L,base);}
}
function researchPlan(L,selection){
 const base=api.gettop(L),out={ready:false,rows:{}};
 try{
  out.stage='selection';
   if(typeof selection!=='string'||selection.length>1024)return out;
  const wanted=selection===''?[]:selection.split(',').map(Number);
   if(wanted.length>128||wanted.some(n=>!Number.isSafeInteger(n)||n<1||n>9999))return out;
  if(wanted.length===0){out.ready=true;return out;}
  const catalog=rawPath(L,['GameDatas','technique_technique']);
  out.stage='catalog';
  if(catalog===null||api.gettype(L,catalog)!==7)return out;
  const identity=api.touserdata(L,catalog).toString();let rows=techniqueCatalogCache.get(identity);
  if(rows===undefined){
   out.stage='iterator';
   if(api.getmetatable(L,catalog)===0)return out;
   const pairs=pushField(L,api.gettop(L),'__pairs');if(!dataReader(L,pairs))return out;
   api.pushvalue(L,catalog);if(api.pcall(L,1,3,0)!==0)return out;
   const iterator=api.gettop(L)-2,container=iterator+1,key=iterator+2;
   if(!dataReader(L,iterator))return out;
   rows={};let complete=false;
   out.stage='scan';
   for(let count=0;count<4096;count++){
    api.pushvalue(L,iterator);api.pushvalue(L,container);api.pushvalue(L,key);
    if(api.pcall(L,2,2,0)!==0)return out;
    if(api.gettype(L,-2)===0){complete=true;break;}
    const cfg=nativeScalarRow(L,api.gettop(L));
    if(cfg===null||!Number.isSafeInteger(cfg.Type)||!Number.isSafeInteger(cfg.Level)){out.invalid=count;return out;}
    const name=cfg.Type+':'+cfg.Level;if(Object.prototype.hasOwnProperty.call(rows,name))return out;
    rows[name]=cfg;
    api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
   }
   if(!complete)return out;
   techniqueCatalogCache.set(identity,rows);
  }
  const owned=readPath(L,['TechniqueData','Datas'],2,{left:1024}),levels={};
  out.stage='owned';
  if(owned===null||owned.$truncated)return out;
  for(const row of Object.values(owned)){
   if(!row||!Number.isSafeInteger(row.Type)||!Number.isSafeInteger(row.Level))return out;
   levels[row.Type]=row.Level;
  }
  for(const type of wanted){const cfg=rows[type+':'+((levels[type]||0)+1)];if(cfg!==undefined)out.rows[String(type)]=cfg;}
  delete out.stage;out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function signupState(L){
 const base=api.gettop(L),out={};
 try{
  out.current=readPath(L,['SLGEventHandler','m_curEventId'],0,{left:1});
  out.ui=readPath(L,['UIObjectManager','AllUIEventMainPage_SLG','UIState'],1,{left:16});
  const fn=rawPath(L,['UIObjectManager','AllUIEventMainPage_SLG','TUT_GetNewSignupClaimBtn']);
  const capture=fn===null?null:capturedData(L,fn,1,1);
  if(capture===null||api.gettype(L,capture.index)!==5)return out;
  const event=pushField(L,capture.index,'eventData');if(api.gettype(L,event)!==5)return out;
  out.id=fieldValue(L,event,'ID',0);out.server=fieldValue(L,event,'TargetServerId',0);
  out.end=fieldValue(L,event,'EndTime',0);
  const tasks=pushField(L,event,'Tasks');
  if(api.gettype(L,tasks)===5){api.rawgeti(L,tasks,1);const row=api.gettop(L);
   if(api.gettype(L,row)===5)out.task=readTable(L,row,3,{left:128},new Set());}
  if(typeof out.id==='string')out.playerTasks=readPath(L,['EventData','PlayerEventData',out.id,'Tasks'],2,{left:128});
  return out;
 }finally{api.settop(L,base);}
}
function resourcePackUI(L){
 const base=api.gettop(L),out={visible:false,configs:{}};
 try{
  const bag=rawPath(L,['UIObjectManager','ItemBag']);
  if(bag!==null&&api.gettype(L,bag)===5){
   out.visible=viewActive(L,bag,'ItemBag');
   for(const [key,name,depth] of [['tab','curTab',0],['selected','curBagItem',1],['count','useCount',0],
     ['disabled','disableUseBtn',0],['progress','InUseProgress',0]])out[key]=fieldValue(L,bag,name,depth);
   out.rows=readPath(L,['UIObjectManager','ItemBag','bagItems','Res'],2,{left:256});
  }
  const configs=rawPath(L,['ItemData','ItemConfigs']);
  if(configs!==null&&api.gettype(L,configs)===5)for(const id of [1,7]){
   api.rawgeti(L,configs,id);const row=api.gettop(L);out.configs[String(id)]=nativeScalarRow(L,row);api.settop(L,row-1);
  }
  return out;
 }finally{api.settop(L,base);}
}
function hudFunctions(L){
 const base=api.gettop(L),out={ready:false,slots:{}};
 try{
  const hud=rawPath(L,['UIObjectManager','MapHudPanel']);
  const fn=rawPath(L,['UIObjectManager','MapHudPanel','SetFunctionBtn']);
  const capture=fn===null?null:capturedData(L,fn,1,4);
  if(hud===null||capture===null||api.gettype(L,capture.index)!==5)return out;
  const ids={};
  for(let slot=1;slot<=5;slot++){
   const obj=pushField(L,hud,'MapHudPanel_BtnFunc'+slot);
   if(api.gettype(L,obj)!==7)return out;
   const id=api.touserdata(L,obj).toString();if(Object.prototype.hasOwnProperty.call(ids,id))return out;
   ids[id]=slot;
  }
  for(let kind=1;kind<=8;kind++){
   api.rawgeti(L,capture.index,kind);const row=api.gettop(L);
   if(api.gettype(L,row)===5){
    const btn=pushField(L,row,'btn');
    if(api.gettype(L,btn)===7){
     const id=api.touserdata(L,btn).toString();
     if(Object.prototype.hasOwnProperty.call(ids,id))out.slots[String(kind)]=ids[id];
    }
   }
   api.settop(L,row-1);
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function viewActive(L,index,name){
 const top=api.gettop(L);
 try{
  // Closed Lua view tables retain m_visible=true after their Unity object is released.
  // A live view must still own its Unity object; never invoke a game/Unity method.
  // Some views inherit the default visibility and have no own m_visible field.
  if(fieldValue(L,index,'m_visible',0)===false)return false;
  if(api.gettype(L,pushField(L,index,'m_unityObj'))!==7)return false;
  return name!=='PopupMissionComplete'||!missionTipsIdle(L,index);
 }finally{api.settop(L,top);}
}
function visibleViews(L){
 const index=rawPath(L,['UIObjectManager']);const output={};
 if(index===null||api.gettype(L,index)!==5)return null;
 api.pushnil(L);let scanned=0;
 while(api.next(L,index)!==0){
  const key=api.gettype(L,-2)===4?scalar(L,-2):null;
  const valueIndex=api.gettop(L);
   if(typeof key==='string'&&api.gettype(L,valueIndex)===5&&viewActive(L,valueIndex,key))output[key]=true;
  api.settop(L,api.gettop(L)-1);
  if(++scanned>=10000){api.settop(L,api.gettop(L)-1);output.$truncated=true;break;}
 }
 return output;
}
function buildings(L){
 const index=rawPath(L,['CityManager','AllObjs']);const output={};
 if(index===null||api.gettype(L,index)!==5)return null;
 const hud=rawPath(L,['UIObjectManager','MapHudPanel']);
 const city=rawPath(L,['CityManager']);
 const cameraX=hud===null?null:fieldValue(L,hud,'CurViewX',0);
 const cameraY=hud===null?null:fieldValue(L,hud,'CurViewY',0);
 const stationary=city!==null&&fieldValue(L,city,'isAutoFocusing',0)===false
    &&fieldValue(L,city,'isInMyCity',0)===true;
 api.pushnil(L);let count=0;
 while(api.next(L,index)!==0){
  const valueIndex=api.gettop(L);
  if(api.gettype(L,valueIndex)===5){
   const id=fieldValue(L,valueIndex,'id',0);
   if(typeof id==='string'||typeof id==='number'){
     const item={};
     for(const key of ['id','type','lv','state','endTime','totalTime','position','logicPosition','width','length'])item[key]=fieldValue(L,valueIndex,key,1);
     item.selected=fieldValue(L,valueIndex,'isSelected',0)===true;
     const itemTop=api.gettop(L);
     const owner=pushField(L,valueIndex,'cityObj');
     const origin=api.gettype(L,owner)===5?fieldValue(L,owner,'pos',1):null;
     const pos=item.position;
     item.focused=null;
     item.world_x=null;item.world_y=null;
      if(origin&&pos&&Number.isFinite(origin['1'])&&Number.isFinite(origin['2'])
        &&Number.isFinite(pos.x)&&Number.isFinite(pos.y)&&Number.isFinite(cameraX)&&Number.isFinite(cameraY)){
      // Observed city-plane rotation. Queue navigation focuses this ground point at screen center.
      const x=origin['1']+(pos.x-pos.y)*Math.SQRT1_2;
      const y=origin['2']+(pos.x+pos.y)*Math.SQRT1_2;
      item.world_x=x;item.world_y=y;
       item.focused=stationary&&Math.abs(cameraX-x)<0.01&&Math.abs(cameraY-y)<0.01;
      }
      if(item.type===6){
       // A wall's layout position is the city origin, not its selectable gate.
       item.world_x=null;item.world_y=null;item.focused=null;
       const ownerId=api.gettype(L,owner)===5?fieldValue(L,owner,'playerId',0):null;
       const user=rawPath(L,['UserData']);
       const player=user===null?null:fieldValue(L,user,'PlayerID',0);
       const colliders=fieldValue(L,valueIndex,'collidersPos',2);
       const gate=colliders&&colliders.Collider;
       if(Number.isSafeInteger(player)&&ownerId===player&&gate
          &&Number.isFinite(gate['1'])&&Number.isFinite(gate['2'])&&Number.isFinite(gate['3'])){
        item.world_x=gate['1'];item.world_y=gate['3'];item.world_source='gate_collider';
        item.focused=stationary&&Math.abs(cameraX-item.world_x)<0.01&&Math.abs(cameraY-item.world_y)<0.01;
       }
      }
     api.settop(L,itemTop);
     output[String(id)]=item;
   }
  }
  api.settop(L,api.gettop(L)-1);
  if(++count>=300){api.settop(L,api.gettop(L)-1);output.$truncated=true;break;}
 }
 return output;
}
function buildingPlan(L){
 const base=api.gettop(L),out={ready:false,rows:{}};
 try{
  const owned=buildings(L),catalog=rawPath(L,['CityBuildHandler','BuildingTypeLevelKV']);
  if(owned===null||owned.$truncated||catalog===null||api.gettype(L,catalog)!==5)return out;
  for(const [id,b] of Object.entries(owned)){
   if(![1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,28,30,31].includes(b.type)
      ||!Number.isSafeInteger(b.lv)||b.lv<1||b.lv>=25)continue;
   const key=b.type*100+b.lv+1;api.rawgeti(L,catalog,key);const row=api.gettop(L);
   if(api.gettype(L,row)===0){api.settop(L,row-1);continue;}
   if(api.gettype(L,row)!==7)return out;
   const identity=key+':'+api.touserdata(L,row).toString();
   let config=buildingConfigCache.get(identity);
   if(config===undefined){config=nativeScalarRow(L,row);if(config===null)return out;buildingConfigCache.set(identity,config);}
   out.rows[id]=config;api.settop(L,row-1);
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function buildingMenu(L){
 const base=api.gettop(L);
 try{
  const user=rawPath(L,['UserData']);
  const player=user===null?null:fieldValue(L,user,'PlayerID',0);
  const cities=rawPath(L,['CityBuildUIMenu','uiCitys']);
  if(!Number.isSafeInteger(player)||player<=0||cities===null||api.gettype(L,cities)!==5)return {known:false};
  api.pushnumber(L,player);api.rawget(L,cities);const city=api.gettop(L);
  if(api.gettype(L,city)!==5)return {known:false};
  const list=pushField(L,city,'uis');
  if(api.gettype(L,list)!==5)return {known:false};
  let selected=null,count=0;api.pushnil(L);
  while(api.next(L,list)!==0){
   const index=api.gettop(L);
   if(api.gettype(L,index)===5&&fieldValue(L,index,'isSelected',0)===true){
    if(selected!==null)return {known:false};
    const object=pushField(L,index,'bobj');
    if(api.gettype(L,object)!==5||fieldValue(L,object,'isSelected',0)!==true)return {known:false};
    selected={id:fieldValue(L,object,'id',0),type:fieldValue(L,object,'type',0),level:fieldValue(L,object,'lv',0),buttons:[]};
    api.settop(L,index);
    const buttons=pushField(L,index,'btnMaps');
    if(api.gettype(L,buttons)!==5)return {known:false};
    api.pushnil(L);let scanned=0;
    while(api.next(L,buttons)!==0){
     const key=api.gettype(L,-2)===4?scalar(L,-2):null;
     if(typeof key==='string'&&api.gettype(L,-1)===7)selected.buttons.push(key);
     api.settop(L,api.gettop(L)-1);
     if(++scanned>=12){api.settop(L,api.gettop(L)-1);return {known:false};}
    }
    api.settop(L,index);
   }
   api.settop(L,api.gettop(L)-1);
   if(++count>=300){api.settop(L,api.gettop(L)-1);return {known:false};}
  }
  return {known:true,selected};
 }finally{api.settop(L,base);}
}
function readableData(address,length){
 const range=address.isNull()?null:Process.findRangeByAddress(address);
 return range!==null&&range.protection.includes('r')&&address.add(length).compare(range.base.add(range.size))<=0;
}
function capturedData(L,fn,position,count){
 // This installed Lua layout was measured from its own native C API readers.
 // Only closed, rooted data captures are admitted; no closure is invoked.
 if(api.gettype(L,fn)!==6||api.iscfunction(L,fn)!==0)return null;
 const closure=api.topointer(L,fn);
 if(!readableData(closure,56+count*8)||closure.add(8).readU8()!==6
     ||closure.add(24).readU8()!==0||closure.add(40).readU8()!==count
     ||position<1||position>count)return null;
 const proto=closure.add(48).readPointer();
 if(!readableData(proto,16)||proto.add(8).readU8()!==9)return null;
 const upvalue=closure.add(56+8*(position-1)).readPointer();
 if(!readableData(upvalue,40)||upvalue.add(8).readU8()!==10)return null;
 const value=upvalue.add(32).readPointer();
 if(!value.equals(upvalue.add(16))||!readableData(value,16))return null;
 const type=value.add(8).readS32();
 if(![0,1,3,4,5].includes(type))return null;
 if(type===4||type===5){
  const object=value.readPointer();
  if(!readableData(object,16)||object.add(8).readU8()!==type)return null;
 }
 const top=L.add(0x10).readPointer(),base=L.add(0x20).readPointer();
 if(!top.sub(base).equals(ptr(api.gettop(L)*16)))return null;
 // Root a copy in a newly pushed scratch slot. The caller restores its stack top.
 // Game-owned tables, captures and callbacks are never written or executed.
 api.pushnil(L);
 const scratch=L.add(0x10).readPointer().sub(16);
 if(!scratch.equals(top))throw new Error('Scratch stack layout changed');
 Memory.copy(scratch,value,16);
 const index=api.gettop(L);
 if(api.gettype(L,index)!==type)throw new Error('Captured data type changed');
 return {index,cell:upvalue};
}
function materialUI(L){
 const base=api.gettop(L);
 try{
  const view=rawPath(L,['UIObjectManager','EquipMaterial']);
  const output={visible:false,known:false};
  if(view===null||api.gettype(L,view)!==5||!viewActive(L,view,'EquipMaterial'))return output;
  output.visible=true;
  output.building_id=fieldValue(L,view,'buildId',0);
  output.back_to_forge=fieldValue(L,view,'m_bBackToForge',0);
  function capture(name,position,count){
   const fn=pushField(L,view,name),result=capturedData(L,fn,position,count);
   if(result===null)throw new Error('Unconfirmed material capture: '+name);
   return result;
  }
  const left=capture('SwitchTabLeft',2,12),top=capture('SwitchTabTop',1,6);
  const list=capture('GetCurSelectItem',2,2),listCheck=capture('SwitchTabLeft',9,12);
  const topCheck=capture('SwitchTabLeft',7,12),listCheck2=capture('SetListProduce',2,6);
  if(!list.cell.equals(listCheck.cell)||!list.cell.equals(listCheck2.cell)||!top.cell.equals(topCheck.cell))return output;
  output.left=scalar(L,left.index);output.top=scalar(L,top.index);output.list_type=scalar(L,list.index);
  output.capacity=scalar(L,capture('SetLeftProduce',1,2).index);
  output.batch=scalar(L,capture('SetLeftProduce',2,2).index);
  const lists=capture('SetListProduce',1,6);
  if(api.gettype(L,lists.index)!==5)return output;
  api.rawgeti(L,lists.index,1);const rows=api.gettop(L);
  if(api.gettype(L,rows)!==5)return output;
  output.recipes={};
  for(let i=1;i<=4;i++){
   api.rawgeti(L,rows,i);const row=api.gettop(L);
   if(api.gettype(L,row)!==5)return output;
   const item={};
   for(const key of ['ID','itemId','Order','ProduceTime','Quality','CLASS'])item[key]=fieldValue(L,row,key,0);
   output.recipes[String(i)]=item;
  }
  output.known=true;return output;
 }catch(error){return {visible:true,known:false};}
 finally{api.settop(L,base);}
}
function wallUI(L){
 const base=api.gettop(L);
 try{
  const view=rawPath(L,['UIObjectManager','CityUICityWall']);
  const output={visible:false,known:false};
  if(view===null||api.gettype(L,view)!==5||!viewActive(L,view,'CityUICityWall'))return output;
  output.visible=true;output.building_id=fieldValue(L,view,'buildId',0);
  const edit=capturedData(L,pushField(L,view,'OnBtnEdit'),1,2);
  const done=capturedData(L,pushField(L,view,'OnBtnEditDone'),1,2);
  const init=capturedData(L,pushField(L,view,'OnInit'),3,3);
  if(edit===null||done===null||init===null||!edit.cell.equals(done.cell)||!edit.cell.equals(init.cell))return output;
  output.editing=scalar(L,edit.index);
  output.known=typeof output.editing==='boolean'&&typeof output.building_id==='string';
  return output;
 }catch(error){return {visible:true,known:false};}
 finally{api.settop(L,base);}
}
function cityCamera(L){
 const base=api.gettop(L);
 try{
  const hud=rawPath(L,['UIObjectManager','MapHudPanel']);
  const city=rawPath(L,['CityManager']);
  const menu=rawPath(L,['CityBuildUIMenu']);
  if(hud===null||city===null||menu===null)return null;
  return {x:fieldValue(L,hud,'CurViewX',0),y:fieldValue(L,hud,'CurViewY',0),
          moving:fieldValue(L,city,'isAutoFocusing',0),distance:fieldValue(L,menu,'curLodDistance',0)};
 }finally{api.settop(L,base);}
}
function barbarianCamera(L){
 const base=api.gettop(L);
 try{
  const camera=cityCamera(L);if(camera===null)return null;
  camera.worldHeight=readPath(L,['WorldMgr','viewHeight'],0,{left:1});
  camera.corners=readPath(L,['WorldMgr','cameraParams','corners'],2,{left:32});
  camera.wheel=readPath(L,['UIObjectManager','MapHudPanel','isShowWheel'],0,{left:1});
  camera.wheelPrefix=readPath(L,['UIObjectManager','MapHudPanel','showWheelPrefix'],0,{left:1});
  return camera;
 }finally{api.settop(L,base);}
}
function cityResources(L){
 const base=api.gettop(L);
 try{
  const list=rawPath(L,['CityManager','AllObjs']);
  if(list===null||api.gettype(L,list)!==5)return null;
   const output={},objects=new Map();api.pushnil(L);let count=0;
  while(api.next(L,list)!==0){
   const index=api.gettop(L);
   if(api.gettype(L,index)===5){
    const type=fieldValue(L,index,'type',0);
    if([2,3,4,5].includes(type)){
     const item={type};
     for(const key of ['id','rssType','rssValue','rssProduceState','gatherMin','gatherLimit','speedSec'])
      item[key]=fieldValue(L,index,key,0);
      if(typeof item.id!=='string')return null;
      const identity=api.topointer(L,index).toString();
      if(objects.has(item.id)&&objects.get(item.id)!==identity)return null;
      objects.set(item.id,identity);output[item.id]=item;
    }
   }
   api.settop(L,api.gettop(L)-1);
   if(++count>=300)return null;
  }
  return output;
 }finally{api.settop(L,base);}
}
function dataReader(L,index){
 if(api.gettype(L,index)!==6||api.iscfunction(L,index)===0)return false;
 const module=Process.findModuleByAddress(api.tocfunction(L,index));
 return module!==null&&module.name==='libEngineDll.so';
}
function readUnitConfig(L,index,id){
 const base=api.gettop(L);
 try{
  if(api.gettype(L,index)!==7)return null;
  const object=api.touserdata(L,index);
  if(object.isNull())return null;
  const identity=object.readPointer().toString()+':'+id;
  if(unitConfigCache.has(identity))return unitConfigCache.get(identity);
  if(api.getmetatable(L,index)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');
  if(!dataReader(L,pairs))return null;
  api.pushvalue(L,index);
  if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;
  if(!dataReader(L,iterator))return null;
  const wanted=new Set(['Id','Type','Tier','Time','Food','Wood','Stone','Coin','BuildingType','BuildingLevel','TechType','TechLevel','Schema']);
  const output={};let finished=false;
  for(let count=0;count<128;count++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0)return null;
   if(api.gettype(L,-2)===0){finished=true;break;}
   const name=api.gettype(L,-2)===4?scalar(L,-2):null;
   if(wanted.has(name))output[name]=scalar(L,-1);
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  if(!finished||output.Id!==id||[...wanted].some(name=>!Number.isFinite(output[name])))return null;
  if(unitConfigCache.size>=64)unitConfigCache.clear();
  unitConfigCache.set(identity,output);
  return output;
 }finally{api.settop(L,base);}
}
function readDonationConfig(L,index,id){
 const base=api.gettop(L);
 try{
  if(api.gettype(L,index)!==7)return null;
  const object=api.touserdata(L,index);
  if(object.isNull())return null;
  const identity=object.readPointer().toString()+':'+id;
  if(donationConfigCache.has(identity))return donationConfigCache.get(identity);
  if(api.getmetatable(L,index)===0)return null;
  const pairs=pushField(L,api.gettop(L),'__pairs');
  if(!dataReader(L,pairs))return null;
  api.pushvalue(L,index);
  if(api.pcall(L,1,3,0)!==0)return null;
  const iterator=api.gettop(L)-2,state=iterator+1,key=iterator+2;
  if(!dataReader(L,iterator))return null;
  const wanted=new Set(['ID','Type','Level','Class','TechniquePoint','DonateType','DonateValue','DonateGem']);
  const output={};let finished=false;
  for(let count=0;count<128;count++){
   api.pushvalue(L,iterator);api.pushvalue(L,state);api.pushvalue(L,key);
   if(api.pcall(L,2,2,0)!==0)return null;
   if(api.gettype(L,-2)===0){finished=true;break;}
   const name=api.gettype(L,-2)===4?scalar(L,-2):null;
   if(wanted.has(name))output[name]=scalar(L,-1);
   api.pushvalue(L,api.gettop(L)-1);api.replace(L,key);api.settop(L,key);
  }
  if(!finished||output.ID!==id||[...wanted].some(name=>!Number.isFinite(output[name])))return null;
  if(donationConfigCache.size>=64)donationConfigCache.clear();
  donationConfigCache.set(identity,output);return output;
 }finally{api.settop(L,base);}
}
function allianceDonation(L){
 const base=api.gettop(L);
 try{
  const data=rawPath(L,['AllianceResearchData']);
  if(data===null||api.gettype(L,data)!==5)return null;
  const output={recommend:fieldValue(L,data,'RecommendType',0),chances:fieldValue(L,data,'CanDonateTimes',0),
   maximum:fieldValue(L,data,'MaxDonateTimes',0),
   today:fieldValue(L,data,'TodayDonateValue',0),needs_refresh:fieldValue(L,data,'NeedRequrest',0),
   target:null,config:null,detail:null,detail_id:null,page_type:null,
   alliance_visible:false,research_visible:false,detail_visible:false};
  const kind=output.recommend,category=Math.floor(kind/100);
  if(Number.isSafeInteger(kind)&&[1,2,3].includes(category)){
   const list=pushField(L,data,['','BattleResearchList','DevelopResearchList','TerritoryResearchList'][category]);
   if(api.gettype(L,list)===5){
    api.rawgeti(L,list,kind);const target=api.gettop(L);
    if(api.gettype(L,target)===5){
     output.target={};
     for(const key of ['type','level','max_level','science_point','end_time','is_alliance'])
      output.target[key]=fieldValue(L,target,key,0);
     const id=kind*100+output.target.level+1;
     const configs=pushField(L,data,'AllResearchConfig');
     if(api.gettype(L,configs)===5&&Number.isSafeInteger(id)){
      api.rawgeti(L,configs,id);output.config=readDonationConfig(L,api.gettop(L),id);
     }
    }
   }
  }
  for(const [field,name] of [['alliance_visible','AllianceMainPage'],['research_visible','AllianceResearchPage'],
      ['detail_visible','AllianceResearchRequestPage']]){
   const view=rawPath(L,['UIObjectManager',name]);
   output[field]=view!==null&&api.gettype(L,view)===5&&viewActive(L,view,name);
   if(field==='research_visible'&&view!==null&&api.gettype(L,view)===5)output.page_type=fieldValue(L,view,'CurShowType',0);
   if(field==='detail_visible'&&output[field]){
    output.detail_id=fieldValue(L,view,'CurResearchID',0);
    output.detail=fieldValue(L,view,'ResearchInfo',0);
   }
  }
  return output;
 }finally{api.settop(L,base);}
}
function trainingForm(L){
 const base=api.gettop(L);
 try{
  const index=rawPath(L,['UIObjectManager','TrainTroops']);
  const output={visible:false,building_id:null,building_type:null,unit_id:null,tier:null,count:null,max_count:null,
                promoting:null,running:null,info:null,config:null,tiers:{}};
  if(index===null||api.gettype(L,index)!==5)return output;
  output.visible=viewActive(L,index,'TrainTroops');
  for(const [name,key] of Object.entries({building_id:'buildId',building_type:'buildType',unit_id:'unit_unitId',tier:'selectIndex',
       count:'lastValidInputValue',max_count:'maxTrainNum',promoting:'isInPromote',running:'isTraining',info:'isInInfo'}))
   output[name]=fieldValue(L,index,key,0);
  const infos=pushField(L,index,'buildTrainInfos');
  if(api.gettype(L,infos)===5){
   for(let tier=1;tier<=5;tier++){
    api.rawgeti(L,infos,tier);const entry=api.gettop(L);
    const item={known:false,unit_id:null,locked:null};output.tiers[String(tier)]=item;
    if(api.gettype(L,entry)===5){
     item.unit_id=fieldValue(L,entry,'id',0);item.locked=fieldValue(L,entry,'locked',0);
     item.known=Number.isSafeInteger(item.unit_id)&&typeof item.locked==='boolean';
     if(output.visible&&tier===output.tier&&item.known){
      const data=pushField(L,entry,'data');output.config=readUnitConfig(L,data,item.unit_id);
     }
    }
    api.settop(L,infos);
   }
  }
  return output;
 }finally{api.settop(L,base);}
}
function trainingKeyboard(L){
 const base=api.gettop(L);
 try{
  const index=rawPath(L,['UIObjectManager','NumericKeyboardPanel']);
  const output={visible:false,first:null,text:null,min:null,max:null,position:null,title:null,y_offset:null,right_offset:null};
  if(index===null||api.gettype(L,index)!==5)return output;
  output.visible=viewActive(L,index,'NumericKeyboardPanel');
   for(const [name,key] of Object.entries({first:'firstInput',text:'m_inputStr',initial:'m_initValue',min:'m_minValue',max:'m_maxValue',
        position:'m_pos',title:'m_title',y_offset:'yOffset',right_offset:'rightOffsetForce'}))
    output[name]=fieldValue(L,index,key,1);
   for(const [name,key] of Object.entries({dynamic_max:'m_getMaxValue',change_callback:'m_onValueChange',confirm_callback:'m_onConfirm'})){
    const top=api.gettop(L);output[name]=api.gettype(L,pushField(L,index,key))===6;api.settop(L,top);
   }
  return output;
 }finally{api.settop(L,base);}
}
function trainingQueues(L){
 const base=api.gettop(L);
 try{
  const queues=rawPath(L,['UIObjectManager','MapHudPanel','queueDataMap']);
  if(queues===null||api.gettype(L,queues)!==5)return null;
  const output={};
  for(let subtype=1;subtype<=4;subtype++){
   const key='trainingQueue_'+subtype;
   const index=pushField(L,queues,key);
   if(api.gettype(L,index)!==5)return null;
   const status=fieldValue(L,index,'status',0);
   const extra=pushField(L,index,'extraData');
   if(api.gettype(L,extra)!==5)return null;
   output[key]={status,extraData:{buildingId:fieldValue(L,extra,'buildingId',0)}};
   api.settop(L,queues);
  }
  return output;
 }finally{api.settop(L,base);}
}
function caveMailRows(L){
 const base=api.gettop(L),out={ready:false,rows:{}};
 try{
  const rows=rawPath(L,['MailData','Datas','Report']);if(rows===null||api.gettype(L,rows)!==5)return out;
  api.pushnil(L);let count=0;
  while(api.next(L,rows)!==0){
   const mail=api.gettop(L);if(++count>256||api.gettype(L,mail)!==5)return out;
   const row={};for(const key of ['id','box','type','serverId','receiver','time','unread'])row[key]=fieldValue(L,mail,key,0);
   if(typeof row.id!=='string'||Object.hasOwn(out.rows,row.id))return out;
   row.attachments=fieldValue(L,mail,'attachments',3);
   const body=pushField(L,mail,'body');row.body={};
   if(api.gettype(L,body)===5){
    for(const key of ['subType','subParam'])row.body[key]=fieldValue(L,body,key,0);
    row.body.position=fieldValue(L,body,'position',1);
   }
   api.settop(L,body-1);out.rows[row.id]=row;api.settop(L,mail-1);
  }
  out.ready=true;return out;
 }finally{api.settop(L,base);}
}
function mailSummary(L){
 const base=api.gettop(L);
 const output={ready:true,pending:0,unread:0,boxes:{},issues:[]};
 const names=['SystemBox','AllianceBox','Report'];
 const seen=new Map(names.map(name=>[name,new Set()]));
 function invalid(reason){output.ready=false;if(output.issues.length<12)output.issues.push(reason);}
 function scanMail(mail){
  const top=api.gettop(L);
  try{
   const name=fieldValue(L,mail,'box',0);
   if(!seen.has(name))return;
   const id=fieldValue(L,mail,'id',0);
   if(typeof id!=='string'&&!Number.isSafeInteger(id)){invalid(name+':id');return;}
   if(seen.get(name).has(String(id)))return;
   seen.get(name).add(String(id));
   const box=output.boxes[name];box.mails++;
   const unreadFlag=fieldValue(L,mail,'unread',0);
   if(unreadFlag===true)box.unread++;
   else if(unreadFlag!==false)invalid(name+':unread-flag');
   const attachments=pushField(L,mail,'attachments');
   if(api.gettype(L,attachments)===5){
    api.pushnil(L);let count=0;
    while(api.next(L,attachments)!==0){
     const item=api.gettop(L);
     if(api.gettype(L,item)===5){
      const status=fieldValue(L,item,'status',0);
      if(status===0)box.pending++;
      else if(status!==1)invalid(name+':status:'+String(status));
     }
     api.settop(L,api.gettop(L)-1);
     if(++count>=64){api.settop(L,api.gettop(L)-1);invalid(name+':attachment-limit');break;}
    }
   }else if(api.gettype(L,attachments)!==0)invalid(name+':attachments');
  }finally{api.settop(L,top);}
 }
 try{
  const data=rawPath(L,['MailData']);
  if(data===null||api.gettype(L,data)!==5)return null;
  if(fieldValue(L,data,'is_init',0)!==true||fieldValue(L,data,'local_loaded',0)!==true)invalid('loading');
  const groups=pushField(L,data,'Datas');
  if(api.gettype(L,groups)!==5)return null;
  const unread=pushField(L,data,'UnreadCount');
  if(api.gettype(L,unread)!==5)return null;
  for(const name of names){
   // Cached counters can become negative after bulk-read. Count actual mail flags,
   // including typed subgroups, and deduplicate aliases by ID without returning content.
   const counter=fieldValue(L,unread,name,0);
   output.boxes[name]={mails:0,pending:0,unread:0,counter:Number.isInteger(counter)?counter:null};
  }
  api.pushnil(L);let groupCount=0,scanned=0;
  while(api.next(L,groups)!==0){
   const group=api.gettop(L);
   if(api.gettype(L,group)===5){
    api.pushnil(L);
    while(api.next(L,group)!==0){
     const mail=api.gettop(L);
     if(api.gettype(L,mail)===5)scanMail(mail);
     api.settop(L,api.gettop(L)-1);
     if(++scanned>=10000){api.settop(L,api.gettop(L)-1);invalid('mail-limit');break;}
    }
   }
   api.settop(L,api.gettop(L)-1);
   if(++groupCount>=64||scanned>=10000){api.settop(L,api.gettop(L)-1);invalid('group-limit');break;}
  }
  for(const box of Object.values(output.boxes)){
   if(box.mails===0&&box.counter>0)invalid('missing-mail-cache');
   output.pending+=box.pending;output.unread+=box.unread;
  }
  return output;
 }finally{api.settop(L,base);}
}
function drain(L){
 if(busy||queue.length===0||!L.equals(stateSlot.readPointer()))return;
 const originalTop=api.gettop(L);
 if(originalTop<0||originalTop>100000)return;
 busy=true;
 const request=queue.shift();clearTimeout(request.timer);
 try{
  if(request.operation==='catalog'){
   const output={};const pattern=new RegExp(request.pattern,'i');let scanned=0;
   api.pushnil(L);
   while(api.next(L,-10002)!==0){
    const key=api.gettype(L,-2)===4?scalar(L,-2):null;
    if(typeof key==='string'&&pattern.test(key))output[key]=types[api.gettype(L,-1)];
    api.settop(L,api.gettop(L)-1);
    if(++scanned>=30000){api.settop(L,api.gettop(L)-1);output.$truncated=true;break;}
   }
   request.resolve(output);return;
  }
  const values={};
  for(const [key,path]of Object.entries(request.paths)){
   values[key]=readPath(L,path,request.depth,{left:1800});
  }
  request.resolve({pid:Process.id,thread:Process.getCurrentThreadId(),capturedMs:Date.now(),
    arch:Process.arch,luaVersion:readPath(L,['_VERSION'],0,{left:1}),values});
 }catch(error){request.reject(error instanceof Error?error:new Error(String(error)));}
 finally{api.settop(L,originalTop);busy=false;}
}
// Work after an existing game-owned Lua call, while preserving its results.
for(const name of ['pcall','call']){
 Interceptor.attach(pointer(name),{onEnter(args){this.luaState=args[0];},onLeave(){drain(this.luaState);}});
}
rpc.exports.status=()=>({pid:Process.id,arch:Process.arch,stateReady:!stateSlot.readPointer().isNull()});
rpc.exports.snapshot=function(paths,depth){
 if(!paths||Object.keys(paths).length>64)throw new Error('Invalid snapshot request');
 for(const path of Object.values(paths))if(!Array.isArray(path)||path.length<1||path.length>8||path.some(k=>typeof k!=='string'&&!Number.isInteger(k)))throw new Error('Invalid field path');
 if(queue.length>=2)throw new Error('Snapshot queue is full');
 return new Promise((resolve,reject)=>{
  const request={paths,depth:Math.min(Math.max(depth,0),4),resolve,reject};
  request.timer=setTimeout(()=>{const index=queue.indexOf(request);if(index>=0)queue.splice(index,1);reject(new Error('No game-owned Lua call within 5 seconds'));},5000);
  queue.push(request);
 });
};
rpc.exports.catalog=function(pattern){
 if(typeof pattern!=='string'||pattern.length>200)throw new Error('Invalid catalog pattern');
 if(queue.length>=2)throw new Error('Snapshot queue is full');
 return new Promise((resolve,reject)=>{
  const request={operation:'catalog',pattern,resolve,reject};
  request.timer=setTimeout(()=>{const index=queue.indexOf(request);if(index>=0)queue.splice(index,1);reject(new Error('No game-owned Lua call within 5 seconds'));},5000);
  queue.push(request);
 });
};
