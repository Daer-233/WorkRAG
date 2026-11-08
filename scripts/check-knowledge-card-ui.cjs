// Validate the exported offline entry point; no cloud template or chat is modified.
const {chromium}=require('C:/Users/liwj/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const path=require('path'),fs=require('fs'),{pathToFileURL}=require('url')
;(async()=>{
  const folder=path.resolve('output/knowledge-card-v1'), browser=await chromium.launch({channel:'msedge',headless:true})
  const page=await browser.newPage(),errors=[],results=[]
  page.on('pageerror',e=>errors.push(e.message))
  try{
    await page.goto(pathToFileURL(path.join(folder,'preview.html')).href)
    await page.locator('#first-three img').first().waitFor()
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:960})
      await page.locator('#done').click()
      const geometry=await page.evaluate(()=>({
        overflow:document.documentElement.scrollWidth>innerWidth,
        bodyScroll:document.body.scrollHeight>innerHeight+1,
        photos:[...document.querySelectorAll('#first-three .photo')].map(el=>({w:el.getBoundingClientRect().width,h:el.getBoundingClientRect().height})),
        imagesLoaded:[...document.querySelectorAll('#first-three img')].every(el=>el.complete&&el.naturalWidth>0)
      }))
      if(geometry.overflow||geometry.bodyScroll||!geometry.imagesLoaded||geometry.photos.length!==3||geometry.photos.some(p=>p.w>96.1||p.h>64.1))throw Error(JSON.stringify({width,geometry}))
      if(await page.locator('#remaining .photo:visible').count())throw Error('Extra photos visible before expansion')
      await page.locator('#more > summary').click()
      if(await page.locator('#remaining .photo:visible').count()!==8)throw Error('Expected eight remaining photos')
      await page.locator('#photos > summary').click()
      await page.locator('#photos > summary').click()
      if(await page.locator('#remaining .photo:visible').count())throw Error('Reopening did not reset to three photos')
      await page.locator('#first-three .photo').first().click()
      if(!await page.locator('#lightbox').isVisible())throw Error('Missing full-size preview')
      await page.keyboard.press('Escape')
      await page.locator('#answer a').first().click()
      if(!await page.locator('#source-1 .quote').evaluate(el=>el.open))throw Error('Citation did not open original excerpt')
      const rendered=await page.locator('.card').innerText()
      if(rendered.includes('证据 ID')||rendered.includes('见随后发送')||rendered.includes('127.0.0.1'))throw Error('Technical artifacts leaked into card')
      await page.screenshot({path:path.join(folder,`preview-${width}.png`)})
      results.push({width,...geometry})
    }
    await page.locator('#busy').click()
    if(await page.locator('#photos').isVisible()||await page.locator('#sources').isVisible())throw Error('Busy response shows stale evidence')
    await page.locator('#fail').click()
    if(!(await page.locator('#answer').innerText()).length)throw Error('Failure lost existing answer')
    await page.locator('#demo').click()
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='正在生成回答')
    await page.waitForFunction(()=>document.querySelector('#answer').textContent.length>0)
    const partial=await page.locator('#answer').innerText()
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='回答完成',null,{timeout:15000})
    const complete=await page.locator('#answer').innerText()
    if(partial.length>=complete.length)throw Error('Demo did not update in stages')
    await page.emulateMedia({reducedMotion:'reduce'})
    await page.locator('#done').click()
    if(errors.length)throw Error(JSON.stringify(errors))
    const report={passed:true,viewports:results,photos:11,partialLength:partial.length,completeLength:complete.length,pageErrors:errors,
      note:'Offline preview verified. DingTalk cloud import and device rendering not yet verified.'}
    fs.writeFileSync(path.join(folder,'ui-verification.json'),JSON.stringify(report,null,2))
    console.log(JSON.stringify(report))
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)})
