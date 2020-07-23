// SICRMQX.stan
// Latent variable nonlinear SICR model with mitigation and release, q>0

functions {
         // time transition functions for beta and sigmac

         real transition(real base,real location,real transition, real t) {
                 real scale;
                 if (base == 1)
                     scale = 1;
                 else
                    scale = base + (1. - base)/(1. + exp((t - location)/transition));
                 return scale;
         }

         // Relaxation function
         real relax(real base, real t) {
              return base*(1 + 0.42924175/(1 + exp(-0.2154182*(t - 20.29067964))));
         }

         // nonlinear SICR model ODE function
           real[] SICR(
           real t,             // time
           real[] u,           // system state {infected,cases,susceptible}
           real[] theta,       // parameters
           real[] x_r,
           int[] x_i
           )
           {
             real du_dt[5];
             real f1 = theta[1];          // beta - sigmau - sigmac
             real f2 = theta[2];          // beta - sigma u
             real sigmar = theta[3];
             real sigmad =  theta[4];
             real sigmau = theta[5];
             real q = theta[6];
             real mbase = theta[7];
             real mlocation = theta[8];
             real trelax = theta[9];
             real cbase = theta[10];
             real clocation = theta[11];
             real ctransition = theta[12];
             real minit = 1.;


             real sigma = sigmar + sigmad;
             real sigmac = f2/(1+f1);
             real beta = f2 + sigmau;

             real I = u[1];  // infected, latent
             real C = u[2];  // cases, observed
             real Z = u[3];  // total infected

             sigmac *= transition(cbase,clocation,ctransition,t);  // case detection change

             if (t < trelax) {
                beta *= transition(mbase,mlocation,mtransition,t);  // mitigation
             }
             else {
                minit = transition(mbase,mlocation,mtransition,trelax);
                beta *= relax(minit,t-trelax);   // relaxation from lockdown
             }

             du_dt[1] = beta*(I+q*C)*(1-Z) - sigmac*I - sigmau*I; // I
             du_dt[2] = sigmac*I - sigma*C;                       // C
             du_dt[3] = beta*(I+q*C)*(1-Z);                       // Z = N_I cumulative infected
             du_dt[4] = sigmac*I;                                 // N_C cumulative cases
             du_dt[5] = C;                                        // integrated C

             return du_dt;
            }
       }

#include data.stan

transformed data {
    real x_r[0];
    int x_i[0];
    int n_difeq = 5;     // number of differential equations for yhat
    real mtransition = 7.;
    //real q = 0.;
    //real n_pop = 1000;
    //real cbase = 1.;
    //real clocation = 10.;
}

parameters {
    real<lower=0> f1;             // initial infected to case ratio
    real<lower=0> f2;             // f2  beta - sigmau
    real<lower=0> sigmar;         // recovery rate
    real<lower=0> sigmad;         // death rate
    real<lower=0> sigmau;         // I disappearance rate
    real<lower=0> mbase;          // mitigation strength
    real<lower=0> mlocation;      // day of mitigation application
    real<lower=0> trelax;         // day of relaxation from mitigation
    real<lower=0> extra_std;      // phi = 1/extra_std^2 in neg_binomial_2(mu,phi)
    real<lower=0> q;              // infection factor for cases
    real<lower=0> cbase;          // case detection factor
    real<lower=0> clocation;      // day of case change
    real<lower=0> ctransition;    // case detection change transition time
    //real<lower=0> sigmar1;      // 1st compartment recovery rate
    real<lower=1> n_pop;      // population size
}

transformed parameters{
  real lambda[n_total,3]; //neg_binomial_2 rate [new cases, new recovered, new deaths]
  real car[n_total];      //total cases / total infected
  real ifr[n_total];      //total dead / total infected
  real Rt[n_total];           // time dependent reproduction number

  real u_init[5];     // initial conditions for fractions

  real sigmac = f2/(1+f1);
  real beta = f2 + sigmau;
  real sigma = sigmar + sigmad;
  real R0 = beta*(sigma+q*sigmac)/sigma/(sigmac+sigmau);   // reproduction number
  real phi = max([1/(extra_std^2),1e-10]); // likelihood over-dispersion of std

  {
     real theta[12] = {f1, f2, sigmar, sigmad, sigmau, q, mbase, mlocation, trelax, cbase, clocation, ctransition};
     real u[n_total, 5];   // solution from the ODE solver
     real betat;
     real sigmact;

     real cinit = y[1,1]/n_pop;

     u_init[1] = f1*cinit;      // I set from f1 * C initial
     u_init[2] = cinit;         //C  from data
     u_init[3] = u_init[1];     // N_I cumulative infected
     u_init[4] = cinit;         // N_C total cumulative cases
     u_init[5] = cinit;         // integral of active C

     u = integrate_ode_rk45(SICR, u_init, ts[1]-1, ts, theta, x_r, x_i,1e-3,1e-5,2000);

     for (i in 1:n_total){
        car[i] = u[i,4]/u[i,3];
        ifr[i] = sigmad*u[i,5]/u[i,3];
        betat = beta*transition(mbase,mlocation,mtransition,i)*(1-u[i,3]);
        sigmact = sigmac*transition(cbase,clocation,ctransition,i);
        Rt[i] = betat*(sigma+q*sigmact)/sigma/(sigmact+sigmau);
        }

     lambda[1,1] = max([(u[1,4]-u_init[4])*n_pop,0.01]); //C: cases per day
     lambda[1,2] = max([sigmar*(u[1,5]-u_init[5])*n_pop,0.01]); //R: recovered per day
     lambda[1,3] = max([sigmad*(u[1,5]-u_init[5])*n_pop,0.01]); //D: dead per day

     for (i in 2:n_total){
        lambda[i,1] = max([(u[i,4]-u[i-1,4])*n_pop,0.01]); //C: cases per day
        lambda[i,2] = max([sigmar*(u[i,5]-u[i-1,5])*n_pop,0.01]); //R: recovered rate per day
        lambda[i,3] = max([sigmad*(u[i,5]-u[i-1,5])*n_pop,0.01]); //D: dead rate per day
        }
    }
}


model {
//priors Stan convention:  gamma(shape,rate), inversegamma(shape,rate)
/*
#include priorcore.stan
#include priorM.stan
#include priorQ.stan
#include priorPop.stan
#include priorC.stan
*/


    f1 ~ gamma(2.4,.1);                  // f1  initital infected to case ratio
    f2 ~ gamma(175,420.);                 // f2  beta - sigmau
    sigmar ~ gamma(16.,120.);             // sigmar
    sigmad ~ exponential(20.);             // sigmad
    sigmau ~ gamma(2.,23.);                // sigmau
    q ~ exponential(2.);                   // q
    mbase ~ exponential(3.);               // mbase
    mlocation ~ lognormal(log(tm+5),1.);   // mlocation
    extra_std ~ gamma(394.,656.);           // likelihood over dispersion std
    cbase ~ exponential(.2);               // cbase
    clocation ~ lognormal(log(50.),2.);    // clocation
    ctransition ~ gamma(2.,.1);            // ctransition
    n_pop ~ lognormal(log(1e6),4.);        // population
    trelax ~ lognormal(log(tm+50),1.);      // trelax
    //sigmar1 ~ inv_gamma(4.,.2);            // sigmar1

//likelihood
#include likelihood.stan
}

#include generatedquantitiesX.stan
