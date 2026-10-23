// Numerical discovery search; not an impossibility proof.
// Positive magnitudes plus +/- exponents cover unary signs over real values.
// Long-double finite range/rounding can lose candidates. Validate independently.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <string>
#include <vector>
using F=long double;
struct Entry { F v; uint32_t l=0,r=0; uint8_t k=0; char op='L'; };
std::vector<Entry> tables[9][10];
std::string digits="123456789";
uint64_t pairs=0,generated=0,queries=0;
F target=10958, best=std::numeric_limits<F>::infinity();
int first=0;
struct Candidate { F v; std::string e; };
std::string expression(int i,int j,uint32_t n) {
    auto& e=tables[i][j][n];
    if(e.op=='L')return digits.substr(i,j-i);
    auto a=expression(i,e.k,e.l),b=expression(e.k,j,e.r);
    if(e.op=='D')return "(-"+a+"+"+b+")";
    if(e.op=='N')return "("+a+"^(-"+b+"))";
    return "("+a+e.op+b+")";
}
void build(int i,int j) {
    auto& out=tables[i][j];
    auto put=[&](F v,uint32_t x,uint32_t y,int k,char op) {
        if(v>=0 && std::isfinite(v)) { out.push_back({v,x,y,uint8_t(k),op});++generated; }
    };
    put(std::stold(digits.substr(i,j-i)),0,0,0,'L');
    for(int k=i+1;k<j;++k) {
        auto& a=tables[i][k];auto& b=tables[k][j];
        for(uint32_t x=0;x<a.size();++x)for(uint32_t y=0;y<b.size();++y) {
            ++pairs;
            F p=a[x].v,q=b[y].v;
            put(p+q,x,y,k,'+');
            put(std::abs(p-q),x,y,k,p>=q?'-':'D');
            F z=p*q;
            if(z || !p || !q)put(z,x,y,k,'*');
            if(q) { z=p/q; if(z || !p)put(z,x,y,k,'/'); }
            if(p || q) {
                z=std::pow(p,q);
                if(z || !p)put(z,x,y,k,'^');
                if(p) {
                    z=std::pow(p,-q);
                    if(z)put(z,x,y,k,'N');
                }
            }
        }
    }
    std::sort(out.begin(),out.end(),[](const Entry&a,const Entry&b){return a.v<b.v;});
    out.erase(std::unique(out.begin(),out.end(),[](const Entry&a,const Entry&b){return a.v==b.v;}),out.end());
    out.shrink_to_fit();
}
std::optional<Candidate> combine(const Candidate& a,const Candidate& b,char op) {
    F v=0;
    switch(op) {
        case '+':v=a.v+b.v;break;
        case '-':v=a.v-b.v;break;
        case 'D':v=b.v-a.v;break;
        case '*':v=a.v*b.v;if(v==0 && a.v && b.v)return {};break;
        case '/':if(!b.v)return {};v=a.v/b.v;if(v==0 && a.v)return {};break;
        case '^':if(!a.v && !b.v)return {};v=std::pow(a.v,b.v);if(!v && a.v)return {};break;
        case 'N':if(!a.v)return {};v=std::pow(a.v,-b.v);if(!v)return {};break;
    }
    if(v<0 || !std::isfinite(v))return {};
    std::string s;
    if(op=='D')s="(-"+a.e+"+"+b.e+")";
    else if(op=='N')s="("+a.e+"^(-"+b.e+"))";
    else s="("+a.e+op+b.e+")";
    return Candidate{v,s};
}
std::vector<Candidate> search(int i,int j,F goal);
std::vector<Candidate> lookup(int i,int j,F goal) {
    ++queries;
    if(!std::isfinite(goal) || goal<0)return {};
    if(j-i>7)return search(i,j,goal);
    auto& t=tables[i][j];
    auto it=std::lower_bound(t.begin(),t.end(),goal,[](const Entry& e,F v){return e.v<v;});
    auto pos=it-t.begin();
    std::vector<Candidate> out;
    for(auto n=std::max<ptrdiff_t>(0,pos-2);n<std::min<ptrdiff_t>(t.size(),pos+3);++n)
        out.push_back({t[n].v,expression(i,j,n)});
    return out;
}
std::vector<Candidate> search(int i,int j,F goal) {
    std::vector<Candidate> winners;
    F localbest=std::numeric_limits<F>::infinity();
    auto check=[&](std::optional<Candidate> c) {
        if(!c)return;
        F error=std::abs(c->v-goal);
        if(i==first && j==9 && (error<best || error<1e-8L)) {
            std::cout<<"HIT\t"<<std::setprecision(25)<<c->v<<"\t"<<error<<"\t"<<c->e<<"\n";
            best=std::min(best,error);
        }
        if(error<localbest) { localbest=error;winners.clear();winners.push_back(*c); }
        else if(error==localbest && winners.size()<10)winners.push_back(*c);
    };
    check(Candidate{std::stold(digits.substr(i,j-i)),digits.substr(i,j-i)});
    for(int k=i+1;k<j;++k) {
        auto& a=tables[i][k];auto& b=tables[k][j];
        bool leftsmall=j-k>7 || (k-i<=7 && a.size()<=b.size());
        if(leftsmall) {
            for(uint32_t x=0;x<a.size();++x) {
                Candidate p{a[x].v,expression(i,k,x)};
                auto test=[&](F wanted,char op) {
                    for(auto& q:lookup(k,j,wanted))check(combine(p,q,op));
                };
                if(goal>=p.v)test(goal-p.v,'+');
                if(p.v>=goal)test(p.v-goal,'-');
                test(goal+p.v,'D');
                if(p.v) {
                    test(goal/p.v,'*');
                    if(goal)test(p.v/goal,'/');
                    if(goal>0 && p.v!=1) {
                        F e=std::log(goal)/std::log(p.v);
                        test(std::abs(e),e>=0?'^':'N');
                    }
                }
            }
        } else {
            for(uint32_t y=0;y<b.size();++y) {
                Candidate q{b[y].v,expression(k,j,y)};
                auto test=[&](F wanted,char op) {
                    for(auto& p:lookup(i,k,wanted))check(combine(p,q,op));
                };
                if(goal>=q.v)test(goal-q.v,'+');
                test(goal+q.v,'-');
                if(q.v>=goal)test(q.v-goal,'D');
                if(q.v) {
                    test(goal/q.v,'*');
                    test(goal*q.v,'/');
                    if(goal>0) {
                        test(std::pow(goal,1/q.v),'^');
                        test(std::pow(goal,-1/q.v),'N');
                    }
                }
            }
        }
    }
    return winners;
}
int main(int argc,char**argv) {
    std::cout.setf(std::ios::unitbuf);
    if(argc>2 && std::string(argv[1])=="--suffix") {
        first=1;target=std::stold(argv[2]);
    } else if(argc>1)target=std::stold(argv[1]);
    auto start=std::chrono::steady_clock::now();
    for(int n=1;n<=7;++n)for(int i=0;i+n<=9;++i) {
        build(i,i+n);
        std::cout<<digits.substr(i,n)<<": "<<tables[i][i+n].size()<<" numerical magnitudes\n";
    }
    uint64_t states=0;for(auto& row:tables)for(auto& t:row)states+=t.size();
    std::cout<<"States: "<<states<<"; pairs: "<<pairs<<"; generated: "<<generated<<"\n";
    std::cout<<"Search digits: "<<digits.substr(first)<<"\n";
    auto results=search(first,9,target);
    std::cout<<"Best error: "<<std::setprecision(25)<<best<<"; queries: "<<queries<<"\n";
    for(auto& c:results)std::cout<<"BEST\t"<<c.v<<"\t"<<c.e<<"\n";
    std::cout<<"Seconds: "<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<"\n";
}
