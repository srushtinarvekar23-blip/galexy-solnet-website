(function(){
 const nav=document.querySelector('.nav'),tg=document.querySelector('.menu-toggle');
 if(tg)tg.addEventListener('click',()=>nav.classList.toggle('is-open'));
 const c=document.getElementById('carousel');
 if(c){const s=[...c.querySelectorAll('.hslide')],d=[...c.querySelectorAll('.dot')],cnt=c.querySelector('.counter b');let i=0,t;
  const go=n=>{s[i].classList.remove('active');d[i].classList.remove('active');i=(n+s.length)%s.length;s[i].classList.add('active');void d[i].offsetWidth;d[i].classList.add('active');if(cnt)cnt.textContent=String(i+1).padStart(2,'0')};
  const run=()=>{clearInterval(t);t=setInterval(()=>go(i+1),5000)};
  d.forEach((b,k)=>b.addEventListener('click',()=>{go(k);run()}));
  c.querySelector('.prev').addEventListener('click',()=>{go(i-1);run()});c.querySelector('.next').addEventListener('click',()=>{go(i+1);run()});
  document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'){go(i+1);run()}if(e.key==='ArrowLeft'){go(i-1);run()}});run();}
 const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.1});
 document.querySelectorAll('.reveal').forEach((el,k)=>{el.style.transitionDelay=(k%3)*90+'ms';io.observe(el)});
})();
