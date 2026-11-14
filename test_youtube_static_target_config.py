from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).parent


class YouTubeStaticTargetConfigTests(unittest.TestCase):
    def test_frontend_points_to_dedicated_youtube_static_target(self):
        config = (ROOT / "site/assets/config.js").read_text()
        self.assertIn(
            'youtubeStaticBase: "https://holoviewer-youtube-static-assets.singlebagel.workers.dev"',
            config,
        )

    def test_csp_allows_dedicated_youtube_static_target(self):
        headers = (ROOT / "site/_headers").read_text()
        self.assertIn(
            "https://holoviewer-youtube-static-assets.singlebagel.workers.dev",
            headers,
        )

    def test_shared_frontend_gate4_deployer_is_absent(self):
        self.assertFalse(
            (ROOT / "scripts/run_youtube_static_assets_gate4_production.sh").exists()
        )


    def test_video_metadata_resolver_static_video_index_fallback(self):
        resolver = ROOT / "site/assets/video-metadata-resolver.js"
        subprocess.run(["node", "--check", str(resolver)], cwd=ROOT, check=True)
        script = r"""
const fs=require('fs');
global.window={HOLOVIEWER_CONFIG:{
  apiBase:'https://api.test',
  youtubeStaticBase:'https://static.test'
}};
const id='yXjPu4K1Vkg';
const calls=[];
const payloads=new Map([
 ['https://api.test/v1/catalog/videos/'+id,{status:404,payload:{error:'not_found'}}],
 ['https://api.test/v1/videos/'+id+'/metadata',{status:404,payload:{error:'metadata_not_found_cached'}}],
 ['https://static.test/youtube/v1/manifest.json',{status:200,payload:{
   schema_version:1,
   availability:{month_state:{'2026-04':'published'}},
   video_indexes:[{prefix:'y',path:'youtube/v1/objects/video-indexes/video-sha.json'}],
   months:[{month:'2026-04',path:'youtube/v1/objects/months/month-sha.json'}]
 }}],
 ['https://static.test/youtube/v1/objects/video-indexes/video-sha.json',{status:200,payload:{
   schema_version:1,index_version:1,prefix:'y',videos:{[id]:'2026-04'}
 }}],
 ['https://static.test/youtube/v1/objects/months/month-sha.json',{status:200,payload:{
   schema_version:1,month:'2026-04',videos:[{
     video_id:id,actual_start:'2026-04-26T12:01:39Z',
     actual_end:'2026-04-26T14:25:28Z',is_live:1,availability:'public'
   }]
 }}]
]);
global.fetch=async function(url){
 calls.push(url);
 const hit=payloads.get(String(url));
 if(!hit)throw new Error('unexpected fetch '+url);
 return {status:hit.status,ok:hit.status>=200&&hit.status<300,json:async()=>hit.payload};
};
eval(fs.readFileSync('site/assets/video-metadata-resolver.js','utf8'));
(async()=>{
 const result=await window.HoloViewerVideoMetadata.resolve(id,{
   apiBase:'https://api.test',
   youtubeStaticBase:'https://static.test',
   waitForRecovery:false,maxAttempts:1
 });
 if(result.status!=='ready')throw new Error('status='+result.status);
 if(result.source!=='youtube-static-video-index')throw new Error('source='+result.source);
 if(result.row.actual_start!=='2026-04-26T12:01:39Z')throw new Error('start mismatch');
 if(result.row.actual_end!=='2026-04-26T14:25:28Z')throw new Error('end mismatch');
 const expected=[
  'https://api.test/v1/catalog/videos/'+id,
  'https://api.test/v1/videos/'+id+'/metadata',
  'https://static.test/youtube/v1/manifest.json',
  'https://static.test/youtube/v1/objects/video-indexes/video-sha.json',
  'https://static.test/youtube/v1/objects/months/month-sha.json'
 ];
 if(JSON.stringify(calls)!==JSON.stringify(expected))throw new Error('calls='+JSON.stringify(calls));
 console.log('STATIC_VIDEO_INDEX_FALLBACK=PASS');
})().catch(error=>{console.error(error);process.exit(1)});
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("STATIC_VIDEO_INDEX_FALLBACK=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
