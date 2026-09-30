from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from sqlalchemy import or_
import os, re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY','dev-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL','sqlite:///applyflow.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db=SQLAlchemy(app); login=LoginManager(app); login.login_view='login'

STATUSES=['Saved','Applied','Recruiter Screen','Interview','Technical Interview','Final Interview','Offer','Rejected','Withdrawn']
PRIORITIES=['Low','Medium','High']

class User(UserMixin,db.Model):
    id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(160),unique=True,nullable=False); password=db.Column(db.String(255),nullable=False)
class Application(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    company=db.Column(db.String(120),nullable=False,index=True); position=db.Column(db.String(160),nullable=False,index=True); job_url=db.Column(db.String(500),default='')
    salary=db.Column(db.String(100),default=''); location=db.Column(db.String(120),default=''); work_arrangement=db.Column(db.String(30),default='Hybrid'); employment_type=db.Column(db.String(40),default='Full-time')
    date_applied=db.Column(db.Date,nullable=True,index=True); source=db.Column(db.String(80),default=''); recruiter=db.Column(db.String(120),default=''); contact_email=db.Column(db.String(160),default='')
    status=db.Column(db.String(40),default='Saved',index=True); priority=db.Column(db.String(20),default='Medium'); notes=db.Column(db.Text,default=''); skills=db.Column(db.Text,default='')
    next_action=db.Column(db.String(255),default=''); follow_up_date=db.Column(db.Date,nullable=True,index=True); resume_version=db.Column(db.String(120),default=''); cover_letter=db.Column(db.String(120),default='')
    created_at=db.Column(db.DateTime,default=datetime.utcnow); updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
class Activity(db.Model):
    id=db.Column(db.Integer,primary_key=True); application_id=db.Column(db.Integer,db.ForeignKey('application.id'),nullable=False,index=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    kind=db.Column(db.String(40),default='Note'); text=db.Column(db.Text,nullable=False); created_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)

@login.user_loader
def load(uid): return db.session.get(User,int(uid))
def own_app(app_id): return Application.query.filter_by(id=app_id,user_id=current_user.id).first_or_404()
def parse_date(v): return datetime.strptime(v,'%Y-%m-%d').date() if v else None

def dashboard_metrics():
    rows=Application.query.filter_by(user_id=current_user.id).all(); total=len(rows); interviews=sum(r.status in ['Interview','Technical Interview','Final Interview'] for r in rows); offers=sum(r.status=='Offer' for r in rows); rejected=sum(r.status=='Rejected' for r in rows)
    applied=[r for r in rows if r.status!='Saved']; response=sum(r.status not in ['Saved','Applied'] for r in rows); now=date.today(); month_start=now.replace(day=1)
    return dict(total=total,month=sum((r.date_applied or r.created_at.date())>=month_start for r in rows),interviews=interviews,offers=offers,rejected=rejected,response_rate=(response/len(applied)*100 if applied else 0),interview_rate=(interviews/len(applied)*100 if applied else 0))

@app.route('/')
def index(): return redirect(url_for('dashboard')) if current_user.is_authenticated else redirect(url_for('login'))
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        email=request.form['email'].strip().lower()
        if User.query.filter_by(email=email).first(): flash('Email already registered.'); return redirect(url_for('register'))
        u=User(email=email,password=generate_password_hash(request.form['password'])); db.session.add(u); db.session.commit(); login_user(u); return redirect(url_for('dashboard'))
    return render_template('auth.html',mode='Create account')
@app.route('/login',methods=['GET','POST'])
def login_view():
    if request.method=='POST':
        u=User.query.filter_by(email=request.form['email'].strip().lower()).first()
        if u and check_password_hash(u.password,request.form['password']): login_user(u); return redirect(url_for('dashboard'))
        flash('Invalid email or password.')
    return render_template('auth.html',mode='Sign in')
app.add_url_rule('/login','login',login_view,methods=['GET','POST'])
@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    rows=Application.query.filter_by(user_id=current_user.id).order_by(Application.updated_at.desc()).all(); m=dashboard_metrics(); counts={s:sum(r.status==s for r in rows) for s in STATUSES}; upcoming=Application.query.filter(Application.user_id==current_user.id,Application.follow_up_date!=None,Application.follow_up_date>=date.today()).order_by(Application.follow_up_date).limit(6).all()
    recent=Activity.query.filter_by(user_id=current_user.id).order_by(Activity.created_at.desc()).limit(7).all(); labels=[]; values=[]
    for i in range(5,-1,-1):
        d=(date.today().replace(day=1)-timedelta(days=i*30)).replace(day=1); labels.append(d.strftime('%b')); values.append(sum((r.date_applied and r.date_applied.year==d.year and r.date_applied.month==d.month) for r in rows))
    return render_template('dashboard.html',m=m,counts=counts,upcoming=upcoming,recent=recent,labels=labels,values=values,rows=rows)

@app.route('/applications')
@login_required
def applications():
    q=request.args.get('q','').strip(); status=request.args.get('status',''); priority=request.args.get('priority',''); view=request.args.get('view','table')
    query=Application.query.filter_by(user_id=current_user.id)
    if q: query=query.filter(or_(Application.company.ilike(f'%{q}%'),Application.position.ilike(f'%{q}%'),Application.skills.ilike(f'%{q}%')))
    if status: query=query.filter_by(status=status)
    if priority: query=query.filter_by(priority=priority)
    rows=query.order_by(Application.updated_at.desc()).all()
    return render_template('applications.html',rows=rows,statuses=STATUSES,priorities=PRIORITIES,view=view,q=q,status=status,priority=priority)

@app.route('/applications/new',methods=['GET','POST'])
@login_required
def new_application():
    if request.method=='POST':
        f=request.form; a=Application(user_id=current_user.id,company=f['company'],position=f['position'],job_url=f.get('job_url',''),salary=f.get('salary',''),location=f.get('location',''),work_arrangement=f.get('work_arrangement','Hybrid'),employment_type=f.get('employment_type','Full-time'),date_applied=parse_date(f.get('date_applied')),source=f.get('source',''),recruiter=f.get('recruiter',''),contact_email=f.get('contact_email',''),status=f.get('status','Saved'),priority=f.get('priority','Medium'),notes=f.get('notes',''),skills=f.get('skills',''),next_action=f.get('next_action',''),follow_up_date=parse_date(f.get('follow_up_date')),resume_version=f.get('resume_version',''),cover_letter=f.get('cover_letter',''))
        db.session.add(a); db.session.flush(); db.session.add(Activity(application_id=a.id,user_id=current_user.id,kind='Created',text=f'Application created with status {a.status}.')); db.session.commit(); flash('Application added.'); return redirect(url_for('application_detail',app_id=a.id))
    return render_template('application_form.html',a=None,statuses=STATUSES,priorities=PRIORITIES,today=date.today().isoformat())

@app.route('/applications/<int:app_id>')
@login_required
def application_detail(app_id):
    a=own_app(app_id); acts=Activity.query.filter_by(application_id=a.id,user_id=current_user.id).order_by(Activity.created_at.desc()).all(); return render_template('application_detail.html',a=a,activities=acts,statuses=STATUSES)
@app.route('/applications/<int:app_id>/edit',methods=['GET','POST'])
@login_required
def edit_application(app_id):
    a=own_app(app_id)
    if request.method=='POST':
        old=a.status; f=request.form
        for field in ['company','position','job_url','salary','location','work_arrangement','employment_type','source','recruiter','contact_email','status','priority','notes','skills','next_action','resume_version','cover_letter']: setattr(a,field,f.get(field,'') or ('Medium' if field=='priority' else ''))
        a.date_applied=parse_date(f.get('date_applied')); a.follow_up_date=parse_date(f.get('follow_up_date'))
        if old!=a.status: db.session.add(Activity(application_id=a.id,user_id=current_user.id,kind='Status',text=f'Status changed from {old} to {a.status}.'))
        db.session.commit(); flash('Application updated.'); return redirect(url_for('application_detail',app_id=a.id))
    return render_template('application_form.html',a=a,statuses=STATUSES,priorities=PRIORITIES,today=date.today().isoformat())
@app.post('/applications/<int:app_id>/activity')
@login_required
def add_activity(app_id):
    a=own_app(app_id); text=request.form.get('text','').strip()
    if text: db.session.add(Activity(application_id=a.id,user_id=current_user.id,kind=request.form.get('kind','Note'),text=text)); db.session.commit(); flash('Activity added.')
    return redirect(url_for('application_detail',app_id=a.id))
@app.post('/applications/<int:app_id>/status')
@login_required
def quick_status(app_id):
    a=own_app(app_id); new=request.form.get('status'); old=a.status
    if new in STATUSES and new!=old: a.status=new; db.session.add(Activity(application_id=a.id,user_id=current_user.id,kind='Status',text=f'Status changed from {old} to {new}.')); db.session.commit()
    return redirect(request.referrer or url_for('applications'))
@app.post('/applications/<int:app_id>/delete')
@login_required
def delete_application(app_id):
    a=own_app(app_id); Activity.query.filter_by(application_id=a.id,user_id=current_user.id).delete(); db.session.delete(a); db.session.commit(); flash('Application deleted.'); return redirect(url_for('applications'))

@app.route('/analyser',methods=['GET','POST'])
@login_required
def analyser():
    result=None; jd=''; candidate=''
    if request.method=='POST':
        jd=request.form.get('job_description',''); candidate=request.form.get('candidate_skills','')
        tech=['python','java','javascript','typescript','react','next.js','node.js','django','fastapi','flask','sql','postgresql','mysql','aws','azure','docker','kubernetes','git','github','rest','graphql','linux','windows','servicenow','power bi','c++','.net','c#']
        found=[t for t in tech if re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',jd,re.I)]; have=[t for t in found if re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',candidate,re.I)]; missing=[t for t in found if t not in have]
        result=dict(found=found,have=have,missing=missing,match=(len(have)/len(found)*100 if found else 0))
    return render_template('analyser.html',result=result,jd=jd,candidate=candidate)

@app.route('/seed')
@login_required
def seed():
    if not Application.query.filter_by(user_id=current_user.id).first():
        samples=[('Northstar Systems','Junior Software Engineer','Applied','High',10,'Seek','React, TypeScript, REST APIs, PostgreSQL'),('Bluegum Health','IT Support Engineer','Recruiter Screen','High',8,'LinkedIn','Windows, Microsoft 365, ServiceNow, Active Directory'),('Harbour Labs','Full Stack Developer','Technical Interview','High',6,'Company website','Python, Django, React, PostgreSQL, AWS'),('MetroWorks','Application Support Analyst','Rejected','Medium',18,'Seek','SQL, ITSM, troubleshooting'),('Koala Cloud','Graduate Software Engineer','Saved','Medium',0,'LinkedIn','Java, AWS, Git, REST'),('Southern Data','Software Developer','Interview','High',4,'Recruiter','Python, JavaScript, SQL, Azure')]
        for i,(c,p,s,pri,days,src,skills) in enumerate(samples):
            d=date.today()-timedelta(days=days) if days else None; a=Application(user_id=current_user.id,company=c,position=p,status=s,priority=pri,date_applied=d,source=src,skills=skills,location='Melbourne VIC',work_arrangement='Hybrid',next_action='Prepare role-specific examples' if 'Interview' in s or s=='Recruiter Screen' else 'Follow up',follow_up_date=date.today()+timedelta(days=i+1),resume_version='Software Engineering Resume v2')
            db.session.add(a); db.session.flush(); db.session.add(Activity(application_id=a.id,user_id=current_user.id,kind='Created',text=f'Demo application added: {p} at {c}.'))
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/health')
def health(): return jsonify(status='ok')
with app.app_context(): db.create_all()
if __name__=='__main__': app.run(debug=True)
