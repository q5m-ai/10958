// Exact rational search: ordered digits, literal concatenation, + - * / ^,
// and unary negation. Every intermediate reduced numerator/denominator is
// bounded by LIMIT. Irrational and complex intermediates are not represented.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>
using U = uint64_t;
using W = __uint128_t;
constexpr U LIMIT = (U(1)<<63)-1;
struct Q {
    U n, d;
    bool operator==(const Q& b) const { return n==b.n && d==b.d; }
    bool operator!=(const Q& b) const { return !(*this==b); }
};
struct Hash {
    static U mix(U x) { x ^= x>>30; x*=0xbf58476d1ce4e5b9ULL; x^=x>>27; x*=0x94d049bb133111ebULL; return x^(x>>31); }
    size_t operator()(Q a) const { return mix(a.n) ^ mix(a.d+0x9e3779b97f4a7c15ULL); }
};
std::optional<Q> make(W n,W d) {
    if(!d) return {};
    W a=n,b=d;
    while(b) { W r=a%b; a=b; b=r; }
    n/=a; d/=a;
    if(n>LIMIT || d>LIMIT) return {};
    return Q{U(n),U(d)};
}
std::optional<Q> add(Q a,Q b,bool subtract=false) {
    U g=std::gcd(a.d,b.d);
    W x=W(a.n)*(b.d/g), y=W(b.n)*(a.d/g);
    W n=subtract ? (x>=y ? x-y : y-x) : x+y;
    U h=std::gcd(U(n%g),g);
    W d=W(a.d/g)*(b.d/h);
    n/=h;
    if(n>LIMIT || d>LIMIT) return {};
    return Q{U(n),U(d)};
}
std::optional<Q> mul(Q a,Q b,bool divide=false) {
    if(divide) { if(!b.n) return {}; std::swap(b.n,b.d); }
    U g=std::gcd(a.n,b.d), h=std::gcd(b.n,a.d);
    W n=W(a.n/g)*(b.n/h),d=W(a.d/h)*(b.d/g);
    if(n>LIMIT || d>LIMIT) return {};
    return Q{U(n),U(d)};
}
std::optional<U> pow_u(U a,U b,U bound=LIMIT) {
    U r=1;
    while(b) {
        if(b&1) { if(a && r>bound/a) return {}; r*=a; }
        b>>=1;
        if(b) { if(a && a>bound/a) return {}; a*=a; }
    }
    return r;
}
std::optional<U> root_u(U a,U q) {
    if(q==1 || a<=1) return a;
    if(q>=63) return {};
    U guess=U(std::pow((long double)a,1.0L/q)+0.5L);
    U low=guess>2 ? guess-2 : 0;
    U high=guess+2;
    for(U r=low;r<=high;++r) {
        auto v=pow_u(r,q,a);
        if(v && *v==a) return r;
    }
    return {};
}
std::optional<Q> power(Q a,Q b) {
    if(!b.n) { if(!a.n) return {}; return Q{1,1}; }
    if(!a.n) return Q{0,1};
    if(a.n==a.d) return Q{1,1};
    if(b.n>63 || b.d>63) return {};
    auto n=root_u(a.n,b.d),d=root_u(a.d,b.d);
    if(!n || !d) return {};
    auto nn=pow_u(*n,b.n),dd=pow_u(*d,b.n);
    if(!nn || !dd) return {};
    return Q{*nn,*dd};
}
struct Entry { Q q; uint32_t l=0,r=0; uint8_t k=0; char op='L'; };
struct Table {
    std::vector<Entry> v;
    std::unordered_map<Q,uint32_t,Hash> index;
    void put(std::optional<Q> q,uint32_t l,uint32_t r,int k,char op) {
        if(!q) return;
        auto [it,ok]=index.emplace(*q,uint32_t(v.size()));
        if(ok) v.push_back({*q,l,r,uint8_t(k),op});
    }
};
Table tables[9][10];
std::string digits="123456789";
U combinations=0;
std::string expr(int i,int j,uint32_t ix) {
    const Entry& e=tables[i][j].v[ix];
    if(e.op=='L') return digits.substr(i,j-i);
    std::string a=expr(i,e.k,e.l),b=expr(e.k,j,e.r);
    if(e.op=='D') return "(-"+a+"+"+b+")";
    if(e.op=='N') return "("+a+"^(-"+b+"))";
    return "("+a+e.op+b+")";
}
void build(int i,int j) {
    auto& t=tables[i][j];
    t.put(Q{std::stoull(digits.substr(i,j-i)),1},0,0,0,'L');
    for(int k=i+1;k<j;++k) {
        const auto& a=tables[i][k].v; const auto& b=tables[k][j].v;
        for(uint32_t x=0;x<a.size();++x) for(uint32_t y=0;y<b.size();++y) {
            ++combinations;
            Q p=a[x].q,q=b[y].q;
            t.put(add(p,q),x,y,k,'+');
            char op=W(p.n)*q.d>=W(q.n)*p.d ? '-' : 'D';
            t.put(add(p,q,true),x,y,k,op);
            t.put(mul(p,q),x,y,k,'*');
            t.put(mul(p,q,true),x,y,k,'/');
            auto pow=power(p,q);
            t.put(pow,x,y,k,'^');
            if(pow && pow->n) t.put(Q{pow->d,pow->n},x,y,k,'N');
        }
    }
}
using Solution=std::optional<std::string>;
Solution cached(int i,int j,Q target) {
    auto& t=tables[i][j];
    auto it=t.index.find(target);
    if(it==t.index.end()) return {};
    return expr(i,j,it->second);
}
// For target!=0,1, enumerate ALL rational bases/exponents that yield it and
// obey LIMIT. If target=c^g with primitive rational c, bases are c^(+/-k)
// and exponents +/-g/k. All arithmetic here is exact.
Solution power_target(int i,int k,int j,Q target) {
    if(!target.n || target.n==target.d) return {}; // not needed by target tests
    Q c=target; U g=1;
    for(U p=63;p>=2;--p) {
        auto n=root_u(target.n,p),d=root_u(target.d,p);
        if(n && d) { c=Q{*n,*d};g=p;break; }
    }
    Q a{1,1};
    for(U n=1;n<=63;++n) {
        auto next=mul(a,c);
        if(!next) break;
        a=*next;
        auto e=make(g,n);
        auto right=cached(k,j,*e);
        if(!right) continue;
        if(auto left=cached(i,k,a)) return "("+*left+"^"+*right+")";
        if(auto left=cached(i,k,Q{a.d,a.n})) return "("+*left+"^(-"+*right+"))";
    }
    return {};
}
Solution solve(int i,int j,Q target);
Solution solve_split(int i,int k,int j,Q target) {
    auto& a=tables[i][k];auto& b=tables[k][j];
    if(k-i==8 || j-k==8) {
        // These endpoint splits have a single literal digit on the other side.
        if(j-k==8) {
            Q x=a.v[0].q;
            auto test=[&](std::optional<Q> wanted,char op)->Solution {
                if(!wanted) return {};
                auto r=solve(k,j,*wanted); if(!r) return {};
                std::string l=expr(i,k,0);
                if(op=='D') return "(-"+l+"+"+*r+")";
                return "("+l+op+*r+")";
            };
            bool ge=W(target.n)*x.d>=W(x.n)*target.d;
            if(auto s=test(add(target,x,true),ge?'+':'-')) return s;
            if(auto s=test(add(target,x),'D')) return s;
            if(x.n) {
                if(auto s=test(mul(target,x,true),'*')) return s;
                if(auto s=test(mul(x,target,true),'/')) return s;
            }
            // The only leading digit in the nine-digit puzzle is 1; 1^b != T.
            if(x.n!=1 || x.d!=1) throw std::runtime_error("Unsupported endpoint base");
        } else {
            Q y=b.v[0].q;
            auto test=[&](std::optional<Q> wanted,char op)->Solution {
                if(!wanted) return {};
                auto l=solve(i,k,*wanted);if(!l)return {};
                std::string r=expr(k,j,0);
                if(op=='D')return "(-"+*l+"+"+r+")";
                return "("+*l+op+r+")";
            };
            bool ge=W(target.n)*y.d>=W(y.n)*target.d;
            if(auto s=test(add(target,y,true),ge?'+':'D'))return s;
            if(auto s=test(add(target,y),'-'))return s;
            if(y.n)if(auto s=test(mul(target,y,true),'*'))return s;
            if(auto s=test(mul(target,y),'/'))return s;
            auto base=power(target,Q{y.d,y.n});
            if(base) {
                if(auto s=test(base,'^')) return s;
                auto l=solve(i,k,Q{base->d,base->n});
                if(l)return "("+*l+"^(-"+expr(k,j,0)+"))";
            }
        }
        return {};
    }
    if(a.v.size()<=b.v.size()) {
        for(uint32_t x=0;x<a.v.size();++x) {
            Q p=a.v[x].q;
            auto test=[&](std::optional<Q> q,char op)->Solution {
                if(!q)return {};
                auto it=b.index.find(*q);if(it==b.index.end())return {};
                std::string l=expr(i,k,x),r=expr(k,j,it->second);
                if(op=='D')return "(-"+l+"+"+r+")";
                return "("+l+op+r+")";
            };
            bool ge=W(target.n)*p.d>=W(p.n)*target.d;
            if(auto s=test(add(target,p,true),ge?'+':'-'))return s;
            if(auto s=test(add(target,p),'D'))return s;
            if(p.n) {
                if(auto s=test(mul(target,p,true),'*'))return s;
                if(auto s=test(mul(p,target,true),'/'))return s;
            }
        }
    } else {
        for(uint32_t y=0;y<b.v.size();++y) {
            Q q=b.v[y].q;
            auto test=[&](std::optional<Q> p,char op)->Solution {
                if(!p)return {};
                auto it=a.index.find(*p);if(it==a.index.end())return {};
                std::string l=expr(i,k,it->second),r=expr(k,j,y);
                if(op=='D')return "(-"+l+"+"+r+")";
                return "("+l+op+r+")";
            };
            bool ge=W(target.n)*q.d>=W(q.n)*target.d;
            if(auto s=test(add(target,q,true),ge?'+':'D'))return s;
            if(auto s=test(add(target,q),'-'))return s;
            if(q.n) {
                if(auto s=test(mul(target,q,true),'*'))return s;
                if(auto s=test(mul(target,q),'/'))return s;
            }
        }
    }
    return power_target(i,k,j,target);
}
Solution solve(int i,int j,Q target) {
    if(j-i<=7)return cached(i,j,target);
    if(target.d==1 && target.n==std::stoull(digits.substr(i,j-i)))return digits.substr(i,j-i);
    for(int k=i+1;k<j;++k)if(auto s=solve_split(i,k,j,target))return s;
    return {};
}
void checks() {
    auto eq=[](std::optional<Q> q,Q want) { if(!q || !(*q==want))throw std::runtime_error("arithmetic self-test"); };
    eq(add(Q{1,3},Q{1,6}),Q{1,2});
    eq(add(Q{1,6},Q{1,3},true),Q{1,6});
    eq(add(Q{1,3},Q{1,3},true),Q{0,1});
    eq(mul(Q{2,3},Q{9,4}),Q{3,2});
    eq(mul(Q{2,3},Q{9,4},true),Q{8,27});
    eq(power(Q{16,81},Q{3,4}),Q{8,27});
    if(power(Q{2,1},Q{1,2}))throw std::runtime_error("irrational accepted");
    if(power(Q{0,1},Q{0,1}))throw std::runtime_error("0^0 accepted");
    for(U x=0;x<1000;++x) for(U p=1;p<10;++p) {
        auto y=pow_u(x,p);if(y && root_u(*y,p)!=x)throw std::runtime_error("root self-test");
    }
    for(U an=0;an<=20;++an)for(U ad=1;ad<=20;++ad)
    for(U bn=0;bn<=20;++bn)for(U bd=1;bd<=20;++bd) {
        Q a=*make(an,ad),b=*make(bn,bd);
        auto reference=make(W(a.n)*b.d+W(b.n)*a.d,W(a.d)*b.d);
        if(add(a,b)!=reference)throw std::runtime_error("addition differential test");
        W x=W(a.n)*b.d,y=W(b.n)*a.d;
        reference=make(x>y?x-y:y-x,W(a.d)*b.d);
        if(add(a,b,true)!=reference)throw std::runtime_error("subtraction differential test");
        if(mul(a,b)!=make(W(a.n)*b.n,W(a.d)*b.d))throw std::runtime_error("multiplication differential test");
        if(mul(a,b,true)!=make(W(a.n)*b.d,W(a.d)*b.n))throw std::runtime_error("division differential test");
    }
    std::cout<<"Arithmetic self-tests passed\n";
}
int main(int argc,char** argv) {
    std::cout.setf(std::ios::unitbuf);
    checks();
    auto start=std::chrono::steady_clock::now();
    for(int n=1;n<=7;++n) {
        for(int i=0;i+n<=9;++i) {
            build(i,i+n);
            std::cout<<digits.substr(i,n)<<": "<<tables[i][i+n].v.size()<<" magnitudes\n";
        }
    }
    U states=0;for(auto& row:tables)for(auto& t:row)states+=t.v.size();
    std::cout<<"Total states: "<<states<<"; child-value pairs: "<<combinations<<"\n";
    if(argc>1 && std::string(argv[1])=="--dump-small") {
        for(int n=1;n<=4;++n)for(int i=0;i+n<=9;++i)
            for(auto& e:tables[i][i+n].v)
                std::cout<<"VALUE\t"<<digits.substr(i,n)<<"\t"<<e.q.n<<"\t"<<e.q.d<<"\n";
        return 0;
    }
    std::vector<U> goals{10957,10958,10959};
    int first=0;
    if(argc>1 && std::string(argv[1])=="--range") {
        if(argc!=2 && argc!=4)throw std::runtime_error("Usage: exact --range [START END]");
        U lo=argc==4?std::stoull(argv[2]):0,hi=argc==4?std::stoull(argv[3]):11111;
        if(lo>hi || hi>LIMIT)throw std::runtime_error("Invalid range");
        goals.clear();
        for(U n=lo;;++n) { goals.push_back(n);if(n==hi)break; }
    } else if(argc>2 && std::string(argv[1])=="--suffix") {
        first=1;goals.clear();
        for(int n=2;n<argc;++n)goals.push_back(std::stoull(argv[n]));
    } else if(argc>1) {
        goals.clear();for(int n=1;n<argc;++n)goals.push_back(std::stoull(argv[n]));
    }
    std::cout<<"Search digits: "<<digits.substr(first)<<"\n";
    for(U target:goals) {
        auto s=solve(first,9,Q{target,1});
        std::cout<<target<<": "<<(s ? *s : "NOT FOUND")<<"\n";
        if(goals.size()>10000 && target%10000==0)
            std::cerr<<"Completed target "<<target<<" of "<<goals.back()<<"\n";
    }
    auto sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"Seconds: "<<sec<<"; reduced numerator/denominator limit: "<<LIMIT<<"\n";
}
