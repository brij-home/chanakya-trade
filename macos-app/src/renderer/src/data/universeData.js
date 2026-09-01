/**
 * ChanakyaTrade — Comprehensive Institutional Indian Market Universe & Search Engine
 * Covers 500+ Equities (NIFTY 50, Next 50, F&O Universe, Midcaps, Smallcaps),
 * Benchmark & Sectoral Indices, Leading ETFs, MCX Commodities, and Currency Derivatives.
 */

export const INDIAN_UNIVERSE = [
  // ─────────────────────────────────────────────────────────────
  // 1. BENCHMARK & SECTORAL INDICES
  // ─────────────────────────────────────────────────────────────
  { symbol: 'NIFTY50', name: 'NIFTY 50 Benchmark Index', sector: 'Index', subIndustry: 'Benchmark', type: 'index', capTier: 'LARGE', lotSize: 75, isFO: true, aliases: ['nifty', 'nifty 50', 'nifty fifty', 'index', 'benchmark', 'nse'] },
  { symbol: 'BANKNIFTY', name: 'NIFTY Bank Banking Index', sector: 'Banking', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: 30, isFO: true, aliases: ['bank', 'bank nifty', 'nifty bank', 'banknifty'] },
  { symbol: 'FINNIFTY', name: 'NIFTY Financial Services Index', sector: 'Finance', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: 65, isFO: true, aliases: ['fin nifty', 'financial services', 'finnifty'] },
  { symbol: 'MIDCPNIFTY', name: 'NIFTY Midcap Select Index', sector: 'Midcap', subIndustry: 'Benchmark', type: 'index', capTier: 'MID', lotSize: 120, isFO: true, aliases: ['midcap', 'midcap nifty', 'midcpnifty', 'nifty midcap'] },
  { symbol: 'SENSEX', name: 'BSE SENSEX 30 Benchmark Index', sector: 'Index', subIndustry: 'BSE Benchmark', type: 'index', capTier: 'LARGE', lotSize: 20, isFO: true, aliases: ['sensex', 'bse 30', 'bse sensex', 'bombay sensex'] },
  { symbol: 'BANKEX', name: 'BSE BANKEX Banking Index', sector: 'Banking', subIndustry: 'BSE Sectoral', type: 'index', capTier: 'LARGE', lotSize: 15, isFO: true, aliases: ['bankex', 'bse bankex'] },
  { symbol: 'NIFTYNXT50', name: 'NIFTY Next 50 (Junior Nifty)', sector: 'Index', subIndustry: 'Largecap Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['junior nifty', 'nifty next 50', 'next 50'] },
  { symbol: 'NIFTY100', name: 'NIFTY 100 Index', sector: 'Index', subIndustry: 'Broad Market', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['nifty 100', 'top 100'] },
  { symbol: 'NIFTY200', name: 'NIFTY 200 Index', sector: 'Index', subIndustry: 'Broad Market', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['nifty 200'] },
  { symbol: 'NIFTY500', name: 'NIFTY 500 Broad Market Index', sector: 'Index', subIndustry: 'Broad Market', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['nifty 500', 'broad market'] },
  { symbol: 'NIFTYSMLCAP100', name: 'NIFTY Smallcap 100 Index', sector: 'Smallcap', subIndustry: 'Smallcap Index', type: 'index', capTier: 'SMALL', lotSize: null, isFO: false, aliases: ['smallcap 100', 'nifty smallcap'] },
  { symbol: 'INDIAVIX', name: 'India Volatility Index (VIX)', sector: 'Volatility', subIndustry: 'Fear Gauge', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['vix', 'india vix', 'volatility', 'fear index'] },

  // Sectoral Indices
  { symbol: 'NIFTYIT', name: 'NIFTY IT Software Index', sector: 'IT & Tech', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['it', 'tech', 'software', 'nifty it', 'technology'] },
  { symbol: 'NIFTYAUTO', name: 'NIFTY Auto Sector Index', sector: 'Automobiles', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['auto', 'automobiles', 'nifty auto', 'cars', 'oem'] },
  { symbol: 'NIFTYPHARMA', name: 'NIFTY Pharma Healthcare Index', sector: 'Pharma', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['pharma', 'healthcare', 'nifty pharma', 'drugs'] },
  { symbol: 'NIFTYFMCG', name: 'NIFTY FMCG Consumer Goods Index', sector: 'FMCG', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['fmcg', 'consumer', 'nifty fmcg', 'staples'] },
  { symbol: 'NIFTYMETAL', name: 'NIFTY Metal & Mining Index', sector: 'Metals', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['metal', 'mining', 'steel', 'nifty metal', 'aluminium'] },
  { symbol: 'NIFTYREALTY', name: 'NIFTY Realty Real Estate Index', sector: 'Realty', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['realty', 'real estate', 'nifty realty', 'property'] },
  { symbol: 'NIFTYENERGY', name: 'NIFTY Energy Oil & Power Index', sector: 'Energy', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['energy', 'oil', 'gas', 'power', 'nifty energy'] },
  { symbol: 'NIFTYPSU', name: 'NIFTY PSU Bank Index', sector: 'PSU Bank', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['psu bank', 'sbi', 'pnb', 'nifty psu', 'public sector bank'] },
  { symbol: 'NIFTYPVTBANK', name: 'NIFTY Private Bank Index', sector: 'Private Bank', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['pvt bank', 'private bank', 'hdfc', 'icici'] },
  { symbol: 'NIFTYINFRA', name: 'NIFTY Infrastructure Index', sector: 'Infra', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['infra', 'infrastructure', 'nifty infra'] },
  { symbol: 'NIFTYOILGAS', name: 'NIFTY Oil & Gas Index', sector: 'Oil & Gas', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['oil and gas', 'petroleum', 'nifty oil'] },
  { symbol: 'NIFTYCONSUMPTION', name: 'NIFTY India Consumption Index', sector: 'Consumption', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['consumption', 'retail', 'nifty consumption'] },
  { symbol: 'NIFTYMEDIA', name: 'NIFTY Media Entertainment Index', sector: 'Media', subIndustry: 'Sectoral Index', type: 'index', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['media', 'entertainment', 'nifty media'] },

  // ─────────────────────────────────────────────────────────────
  // 2. NIFTY 50 & BLUECHIP EQUITIES (ALL CONSTITUENTS)
  // ─────────────────────────────────────────────────────────────
  { symbol: 'RELIANCE', name: 'Reliance Industries Ltd', sector: 'Energy & Conglomerate', subIndustry: 'Oil, Retail & Telecom', type: 'stock', capTier: 'LARGE', lotSize: 250, isFO: true, aliases: ['ril', 'mukesh ambani', 'jio', 'retail', 'petrochemicals'] },
  { symbol: 'TCS', name: 'Tata Consultancy Services Ltd', sector: 'IT & Software', subIndustry: 'IT Services & Consulting', type: 'stock', capTier: 'LARGE', lotSize: 175, isFO: true, aliases: ['tata consultancy', 'tata it', 'software'] },
  { symbol: 'HDFCBANK', name: 'HDFC Bank Ltd', sector: 'Private Banking', subIndustry: 'Universal Banking', type: 'stock', capTier: 'LARGE', lotSize: 550, isFO: true, aliases: ['hdfc', 'hdfc bank', 'housing development'] },
  { symbol: 'INFY', name: 'Infosys Ltd', sector: 'IT & Software', subIndustry: 'IT Services & Consulting', type: 'stock', capTier: 'LARGE', lotSize: 400, isFO: true, aliases: ['infosys', 'infy', 'narayana murthy'] },
  { symbol: 'ICICIBANK', name: 'ICICI Bank Ltd', sector: 'Private Banking', subIndustry: 'Universal Banking', type: 'stock', capTier: 'LARGE', lotSize: 700, isFO: true, aliases: ['icici', 'icici bank', 'sandeep bakhshi'] },
  { symbol: 'BHARTIARTL', name: 'Bharti Airtel Ltd', sector: 'Telecom', subIndustry: '5G & Data Telecom', type: 'stock', capTier: 'LARGE', lotSize: 950, isFO: true, aliases: ['airtel', 'bharti', 'sunil mittal', '5g'] },
  { symbol: 'SBIN', name: 'State Bank of India', sector: 'PSU Banking', subIndustry: 'PSU Banking Leader', type: 'stock', capTier: 'LARGE', lotSize: 750, isFO: true, aliases: ['sbi', 'state bank', 'state bank of india'] },
  { symbol: 'ITC', name: 'ITC Ltd', sector: 'FMCG & Cigarettes', subIndustry: 'Cigarettes, FMCG & Hotels', type: 'stock', capTier: 'LARGE', lotSize: 1600, isFO: true, aliases: ['itc', 'hotels', 'paperboard', 'sunfeast', 'bingo'] },
  { symbol: 'LT', name: 'Larsen & Toubro Ltd', sector: 'Capital Goods & Infra', subIndustry: 'EPC Engineering', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['l&t', 'larsen', 'infra', 'engineering', 'defense'] },
  { symbol: 'HINDUNILVR', name: 'Hindustan Unilever Ltd', sector: 'FMCG', subIndustry: 'Home & Personal Care', type: 'stock', capTier: 'LARGE', lotSize: 300, isFO: true, aliases: ['hul', 'unilever', 'surf excel', 'dove', 'lux'] },
  { symbol: 'KOTAKBANK', name: 'Kotak Mahindra Bank Ltd', sector: 'Private Banking', subIndustry: 'Universal Banking', type: 'stock', capTier: 'LARGE', lotSize: 400, isFO: true, aliases: ['kotak', 'uday kotak', 'kotak 811'] },
  { symbol: 'AXISBANK', name: 'Axis Bank Ltd', sector: 'Private Banking', subIndustry: 'Universal Banking', type: 'stock', capTier: 'LARGE', lotSize: 625, isFO: true, aliases: ['axis', 'axis bank', 'amitabh chaudhry'] },
  { symbol: 'BAJFINANCE', name: 'Bajaj Finance Ltd', sector: 'NBFC & Lending', subIndustry: 'Consumer & SME Lending', type: 'stock', capTier: 'LARGE', lotSize: 125, isFO: true, aliases: ['bajaj fin', 'consumer finance', 'emi card', 'lending'] },
  { symbol: 'BAJAJFINSV', name: 'Bajaj Finserv Ltd', sector: 'Financial Services', subIndustry: 'Insurance & Holding', type: 'stock', capTier: 'LARGE', lotSize: 500, isFO: true, aliases: ['bajaj finserv', 'finserv', 'allianz', 'life insurance'] },
  { symbol: 'BAJAJ-AUTO', name: 'Bajaj Auto Ltd (2W, 3W & Chetak EV)', sector: 'Automobiles & EV', subIndustry: '2-Wheelers & 3-Wheelers', type: 'stock', capTier: 'LARGE', lotSize: 75, isFO: true, aliases: ['bajaj', 'bajaj auto', 'bajaj-auto', 'bajaj_auto', 'bajajauto', 'pulsar', 'chetak', 'triumph', 'ktm', '2-wheeler'] },
  { symbol: 'MARUTI', name: 'Maruti Suzuki India Ltd', sector: 'Automobiles', subIndustry: 'Passenger Cars (4W)', type: 'stock', capTier: 'LARGE', lotSize: 50, isFO: true, aliases: ['maruti suzuki', 'cars', 'suzuki', 'swift', 'brezza'] },
  { symbol: 'ASIANPAINT', name: 'Asian Paints Ltd', sector: 'Paints & Coatings', subIndustry: 'Decorative Paints', type: 'stock', capTier: 'LARGE', lotSize: 200, isFO: true, aliases: ['asian paints', 'paints', 'royale', 'apex'] },
  { symbol: 'TITAN', name: 'Titan Company Ltd', sector: 'Jewellery & Watches', subIndustry: 'Tanishq & Lifestyle', type: 'stock', capTier: 'LARGE', lotSize: 175, isFO: true, aliases: ['titan', 'tanishq', 'watches', 'fastrack', 'caratlane'] },
  { symbol: 'M&M', name: 'Mahindra & Mahindra Ltd', sector: 'Automobiles & Tractors', subIndustry: 'SUVs & Farm Equipment', type: 'stock', capTier: 'LARGE', lotSize: 350, isFO: true, aliases: ['mahindra', 'm&m', 'suv', 'thar', 'scorpio', 'xuv700', 'tractors'] },
  { symbol: 'SUNPHARMA', name: 'Sun Pharmaceutical Industries Ltd', sector: 'Pharma & Generics', subIndustry: 'Global Formulations & API', type: 'stock', capTier: 'LARGE', lotSize: 350, isFO: true, aliases: ['sun pharma', 'dilip shanghvi', 'generics'] },
  { symbol: 'TATAMOTORS', name: 'Tata Motors Ltd (JLR & EV)', sector: 'Automobiles & EV', subIndustry: 'Commercial & Passenger EV', type: 'stock', capTier: 'LARGE', lotSize: 575, isFO: true, aliases: ['tata motors', 'jlr', 'ev', 'nexon', 'harrier', 'safari'] },
  { symbol: 'NTPC', name: 'NTPC Ltd', sector: 'Power Generation', subIndustry: 'Thermal & Green Power', type: 'stock', capTier: 'LARGE', lotSize: 1500, isFO: true, aliases: ['ntpc', 'power', 'thermal', 'green power'] },
  { symbol: 'ONGC', name: 'Oil and Natural Gas Corporation Ltd', sector: 'Oil Exploration', subIndustry: 'Upstream Crude & Gas', type: 'stock', capTier: 'LARGE', lotSize: 3850, isFO: true, aliases: ['ongc', 'crude oil', 'upstream', 'natural gas'] },
  { symbol: 'POWERGRID', name: 'Power Grid Corporation of India Ltd', sector: 'Power Transmission', subIndustry: 'Inter-State Grid Transmission', type: 'stock', capTier: 'LARGE', lotSize: 2700, isFO: true, aliases: ['powergrid', 'grid', 'transmission'] },
  { symbol: 'ADANIENT', name: 'Adani Enterprises Ltd', sector: 'Conglomerate & Mining', subIndustry: 'Incubator & Airports', type: 'stock', capTier: 'LARGE', lotSize: 300, isFO: true, aliases: ['adani ent', 'gautam adani', 'airports', 'green hydrogen'] },
  { symbol: 'ADANIPORTS', name: 'Adani Ports and Special Economic Zone Ltd', sector: 'Ports & Logistics', subIndustry: 'Commercial Seaports', type: 'stock', capTier: 'LARGE', lotSize: 400, isFO: true, aliases: ['adani ports', 'mundra', 'logistics', 'ports'] },
  { symbol: 'TATASTEEL', name: 'Tata Steel Ltd', sector: 'Metals & Steel', subIndustry: 'Integrated Steel Producer', type: 'stock', capTier: 'LARGE', lotSize: 5500, isFO: true, aliases: ['tata steel', 'steel', 'jamshedpur', 'corus'] },
  { symbol: 'COALINDIA', name: 'Coal India Ltd', sector: 'Mining & Coal', subIndustry: 'Fossil Fuels & Mining', type: 'stock', capTier: 'LARGE', lotSize: 2100, isFO: true, aliases: ['coal', 'cil', 'coal india'] },
  { symbol: 'ULTRACEMCO', name: 'UltraTech Cement Ltd', sector: 'Cement & Building', subIndustry: 'Grey Cement Market Leader', type: 'stock', capTier: 'LARGE', lotSize: 100, isFO: true, aliases: ['ultratech', 'aditya birla', 'cement'] },
  { symbol: 'JSWSTEEL', name: 'JSW Steel Ltd', sector: 'Metals & Steel', subIndustry: 'Steel Manufacturing', type: 'stock', capTier: 'LARGE', lotSize: 675, isFO: true, aliases: ['jsw', 'sajjan jindal', 'steel'] },
  { symbol: 'GRASIM', name: 'Grasim Industries Ltd', sector: 'Conglomerate & Materials', subIndustry: 'VSF, Chemicals & Paints', type: 'stock', capTier: 'LARGE', lotSize: 250, isFO: true, aliases: ['grasim', 'birla opus', 'paints', 'vsf'] },
  { symbol: 'HEROMOTOCO', name: 'Hero MotoCorp Ltd', sector: 'Automobiles & 2W', subIndustry: 'Entry & Commuter 2-Wheelers', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['hero', 'hero motocorp', 'splendor', 'vida ev'] },
  { symbol: 'EICHERMOT', name: 'Eicher Motors Ltd (Royal Enfield)', sector: 'Automobiles & 2W', subIndustry: 'Premium Motorcycles & VECV', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['royal enfield', 'bullet', 'eicher', 'hunter', 'classic 350'] },
  { symbol: 'HCLTECH', name: 'HCL Technologies Ltd', sector: 'IT Services', subIndustry: 'Digital Engineering & Cloud', type: 'stock', capTier: 'LARGE', lotSize: 350, isFO: true, aliases: ['hcl', 'shiv nadar', 'software'] },
  { symbol: 'WIPRO', name: 'Wipro Ltd', sector: 'IT Services', subIndustry: 'IT Consulting & Outsourcing', type: 'stock', capTier: 'LARGE', lotSize: 1500, isFO: true, aliases: ['wipro', 'azim premji', 'software'] },
  { symbol: 'TECHM', name: 'Tech Mahindra Ltd', sector: 'IT Services', subIndustry: 'Telecom 5G Software', type: 'stock', capTier: 'LARGE', lotSize: 600, isFO: true, aliases: ['tech mahindra', 'techm', 'telecom software'] },
  { symbol: 'APOLLOHOSP', name: 'Apollo Hospitals Enterprise Ltd', sector: 'Hospitals & Healthcare', subIndustry: 'Multi-Specialty & Apollo 24/7', type: 'stock', capTier: 'LARGE', lotSize: 125, isFO: true, aliases: ['apollo', 'apollo hospitals', 'pharmacy', 'health'] },
  { symbol: 'DRREDDY', name: 'Dr. Reddys Laboratories Ltd', sector: 'Pharma & Biosimilars', subIndustry: 'Generics & Oncology', type: 'stock', capTier: 'LARGE', lotSize: 125, isFO: true, aliases: ['dr reddy', 'dr reddys', 'biosimilars'] },
  { symbol: 'CIPLA', name: 'Cipla Ltd', sector: 'Pharma & Generics', subIndustry: 'Respiratory & Inhalation', type: 'stock', capTier: 'LARGE', lotSize: 650, isFO: true, aliases: ['cipla', 'respiratory', 'inhalers'] },
  { symbol: 'TRENT', name: 'Trent Ltd (Westside & Zudio)', sector: 'Retail & Fashion', subIndustry: 'Apparel & Fast Fashion', type: 'stock', capTier: 'LARGE', lotSize: 100, isFO: true, aliases: ['zudio', 'westside', 'tata retail', 'star bazaar'] },
  { symbol: 'BEL', name: 'Bharat Electronics Ltd', sector: 'Defense Electronics', subIndustry: 'Radars, Sonar & Avionics', type: 'stock', capTier: 'LARGE', lotSize: 2850, isFO: true, aliases: ['defense', 'radars', 'bharat elec', 'defence psu'] },
  { symbol: 'HAL', name: 'Hindustan Aeronautics Ltd', sector: 'Aerospace & Defense', subIndustry: 'Fighter Jets & Helicopters', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['tejas', 'fighter jets', 'defense', 'hal', 'aerospace'] },
  { symbol: 'ZOMATO', name: 'Zomato Ltd (Blinkit)', sector: 'Quick Commerce & Food', subIndustry: 'Q-Commerce & Food Delivery', type: 'stock', capTier: 'LARGE', lotSize: 2000, isFO: true, aliases: ['blinkit', 'food delivery', 'q-commerce', 'deepinder goyal'] },
  { symbol: 'NESTLEIND', name: 'Nestle India Ltd', sector: 'FMCG & Food', subIndustry: 'Maggi, Infant & Dairy Food', type: 'stock', capTier: 'LARGE', lotSize: 200, isFO: true, aliases: ['nestle', 'maggi', 'nescafe', 'kitkat'] },
  { symbol: 'BRITANNIA', name: 'Britannia Industries Ltd', sector: 'FMCG & Bakery', subIndustry: 'Biscuits & Dairy', type: 'stock', capTier: 'LARGE', lotSize: 200, isFO: true, aliases: ['britannia', 'good day', 'biscuits'] },
  { symbol: 'DIVISLAB', name: 'Divis Laboratories Ltd', sector: 'Pharma API & CRAMS', subIndustry: 'Custom Synthesis & CDMO', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['divis', 'custom synthesis', 'cdmo', 'api'] },
  { symbol: 'HINDALCO', name: 'Hindalco Industries Ltd (Novelis)', sector: 'Metals & Aluminium', subIndustry: 'Aluminium & Copper Rolling', type: 'stock', capTier: 'LARGE', lotSize: 1400, isFO: true, aliases: ['hindalco', 'novelis', 'aluminium', 'aditya birla'] },
  { symbol: 'BPCL', name: 'Bharat Petroleum Corporation Ltd', sector: 'Oil & Gas Refining', subIndustry: 'Downstream Fuel Marketing', type: 'stock', capTier: 'LARGE', lotSize: 1800, isFO: true, aliases: ['bpcl', 'refinery', 'petrol pump', 'fuel'] },
  { symbol: 'SHRIRAMFIN', name: 'Shriram Finance Ltd', sector: 'Vehicle NBFC', subIndustry: 'Commercial Vehicle Lending', type: 'stock', capTier: 'LARGE', lotSize: 300, isFO: true, aliases: ['shriram', 'cv loans', 'truck financing'] },
  { symbol: 'TATACONSUM', name: 'Tata Consumer Products Ltd', sector: 'FMCG & Beverages', subIndustry: 'Tea, Salt & Packaged Foods', type: 'stock', capTier: 'LARGE', lotSize: 900, isFO: true, aliases: ['tata tea', 'tata salt', 'sampann', 'starbucks'] },
  { symbol: 'INDUSINDBK', name: 'IndusInd Bank Ltd', sector: 'Private Banking', subIndustry: 'Vehicle & SME Banking', type: 'stock', capTier: 'LARGE', lotSize: 500, isFO: true, aliases: ['indusind', 'hinduja', 'indusind bank'] },

  // ─────────────────────────────────────────────────────────────
  // 3. F&O DERIVATIVE UNIVERSE & HIGH-MOMENTUM LEADERS
  // ─────────────────────────────────────────────────────────────
  { symbol: 'ABB', name: 'ABB India Ltd', sector: 'Capital Goods & Robotics', subIndustry: 'Industrial Automation & Electrification', type: 'stock', capTier: 'LARGE', lotSize: 125, isFO: true, aliases: ['abb', 'robotics', 'automation'] },
  { symbol: 'SIEMENS', name: 'Siemens Ltd', sector: 'Capital Goods & Infra', subIndustry: 'Energy Grid & Industrial Software', type: 'stock', capTier: 'LARGE', lotSize: 125, isFO: true, aliases: ['siemens', 'grid', 'locomotives'] },
  { symbol: 'POLYCAB', name: 'Polycab India Ltd', sector: 'Wires & Cables & FMEG', subIndustry: 'Cables, Wires & Fast Moving Electrical', type: 'stock', capTier: 'LARGE', lotSize: 125, isFO: true, aliases: ['polycab', 'cables', 'wires'] },
  { symbol: 'KEI', name: 'KEI Industries Ltd', sector: 'Wires & Cables', subIndustry: 'EHV & Power Cables', type: 'stock', capTier: 'MID', lotSize: 150, isFO: true, aliases: ['kei', 'cables', 'wires'] },
  { symbol: 'DIXON', name: 'Dixon Technologies (India) Ltd', sector: 'Electronics & EMS', subIndustry: 'Smartphones & Consumer Electronics', type: 'stock', capTier: 'LARGE', lotSize: 100, isFO: true, aliases: ['dixon', 'ems', 'smartphones', 'pli', 'electronics'] },
  { symbol: 'KAYNES', name: 'Kaynes Technology India Ltd', sector: 'Electronics & EMS', subIndustry: 'Aerospace, Defense & OSAT Semiconductor', type: 'stock', capTier: 'MID', lotSize: 150, isFO: true, aliases: ['kaynes', 'semiconductor', 'osat', 'ems'] },
  { symbol: 'COFORGE', name: 'Coforge Ltd', sector: 'IT & Digital Services', subIndustry: 'Travel & BFSI IT Solutions', type: 'stock', capTier: 'MID', lotSize: 150, isFO: true, aliases: ['coforge', 'midcap it', 'travel tech'] },
  { symbol: 'PERSISTENT', name: 'Persistent Systems Ltd', sector: 'IT & Cloud Engineering', subIndustry: 'AI, Cloud & Health Tech', type: 'stock', capTier: 'MID', lotSize: 100, isFO: true, aliases: ['persistent', 'cloud', 'ai tech'] },
  { symbol: 'KPITTECH', name: 'KPIT Technologies Ltd', sector: 'Automotive Software & SDV', subIndustry: 'Software Defined Vehicles & EV', type: 'stock', capTier: 'MID', lotSize: 400, isFO: true, aliases: ['kpit', 'autonomous software', 'sdv'] },
  { symbol: 'TATAELXSI', name: 'Tata Elxsi Ltd', sector: 'Design & Automotive Tech', subIndustry: 'ER&D & Healthcare Design', type: 'stock', capTier: 'MID', lotSize: 100, isFO: true, aliases: ['elxsi', 'ev design', 'embedded'] },
  { symbol: 'TATATECH', name: 'Tata Technologies Ltd', sector: 'ER&D & Automotive Tech', subIndustry: 'OEM Product Engineering', type: 'stock', capTier: 'MID', lotSize: 500, isFO: true, aliases: ['tata tech', 'engineering'] },
  { symbol: 'OFSS', name: 'Oracle Financial Services Software', sector: 'IT & Software', subIndustry: 'Banking Software Products', type: 'stock', capTier: 'LARGE', lotSize: 100, isFO: true, aliases: ['oracle', 'ofss', 'flexcube'] },
  { symbol: 'MPHASIS', name: 'Mphasis Ltd', sector: 'IT Services', subIndustry: 'Direct BFSI Cloud Solutions', type: 'stock', capTier: 'MID', lotSize: 275, isFO: true, aliases: ['mphasis', 'blackstone'] },
  { symbol: 'LTIM', name: 'LTIMindtree Ltd', sector: 'IT Services', subIndustry: 'Digital Transformation', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['ltimindtree', 'mindtree', 'lti'] },
  { symbol: 'LTTS', name: 'L&T Technology Services Ltd', sector: 'ER&D IT Services', subIndustry: 'Plant & Telecom Engineering', type: 'stock', capTier: 'MID', lotSize: 100, isFO: true, aliases: ['ltts', 'engineering services'] },

  // Exchanges & Brokerages
  { symbol: 'BSE', name: 'BSE Ltd (Bombay Stock Exchange)', sector: 'Capital Markets Exchange', subIndustry: 'Derivatives & Equity Exchange', type: 'stock', capTier: 'MID', lotSize: 375, isFO: true, aliases: ['bombay stock exchange', 'derivatives', 'bse'] },
  { symbol: 'MCX', name: 'Multi Commodity Exchange of India Ltd', sector: 'Commodity Exchange', subIndustry: 'Gold & Crude Futures Platform', type: 'stock', capTier: 'MID', lotSize: 125, isFO: true, aliases: ['gold crude exchange', 'mcx', 'commodity exchange'] },
  { symbol: 'CDSL', name: 'Central Depository Services (India) Ltd', sector: 'Depository & FinTech', subIndustry: 'Demat Account Depository', type: 'stock', capTier: 'MID', lotSize: 400, isFO: true, aliases: ['demat accounts', 'cdsl', 'depository'] },
  { symbol: 'ANGELONE', name: 'Angel One Ltd', sector: 'Fintech & Brokerage', subIndustry: 'Discount Retail Brokerage', type: 'stock', capTier: 'MID', lotSize: 250, isFO: true, aliases: ['angel broking', 'retail broker', 'angelone'] },
  { symbol: 'JIOFIN', name: 'Jio Financial Services Ltd', sector: 'Financial Services & AMC', subIndustry: 'BlackRock JV & Lending', type: 'stock', capTier: 'LARGE', lotSize: 1800, isFO: true, aliases: ['blackrock jio', 'jio fin', 'jfs'] },
  { symbol: 'HDFCAMC', name: 'HDFC Asset Management Co Ltd', sector: 'Asset Management AMC', subIndustry: 'Mutual Funds & Wealth', type: 'stock', capTier: 'LARGE', lotSize: 150, isFO: true, aliases: ['hdfc mutual fund', 'hdfc amc'] },

  // Defence & Shipbuilding
  { symbol: 'MAZDOCK', name: 'Mazagon Dock Shipbuilders Ltd', sector: 'Defense & Naval Ships', subIndustry: 'Submarines & Stealth Frigates', type: 'stock', capTier: 'MID', lotSize: 175, isFO: true, aliases: ['submarines', 'warships', 'defense', 'mazagon'] },
  { symbol: 'COCHINSHIP', name: 'Cochin Shipyard Ltd', sector: 'Defense Shipbuilding', subIndustry: 'Aircraft Carriers & Ship Repair', type: 'stock', capTier: 'MID', lotSize: 350, isFO: true, aliases: ['aircraft carrier', 'vikrant', 'cochin ship'] },
  { symbol: 'BDL', name: 'Bharat Dynamics Ltd', sector: 'Defense & Missiles', subIndustry: 'Akash Missiles & Torpedoes', type: 'stock', capTier: 'MID', lotSize: 300, isFO: true, aliases: ['missiles', 'akash missile', 'bdl'] },
  { symbol: 'DATAPATTNS', name: 'Data Patterns (India) Ltd', sector: 'Defense Electronics', subIndustry: 'Radars & Electronic Warfare', type: 'stock', capTier: 'SMALL', lotSize: null, isFO: false, aliases: ['data patterns', 'radars', 'defense electronics'] },
  { symbol: 'ZENTEC', name: 'Zen Technologies Ltd', sector: 'Defense & Drone Simulators', subIndustry: 'Anti-Drone & Combat Simulators', type: 'stock', capTier: 'SMALL', lotSize: null, isFO: false, aliases: ['zen tech', 'anti-drone', 'simulators'] },
  { symbol: 'SOLARINDS', name: 'Solar Industries India Ltd', sector: 'Defense & Industrial Explosives', subIndustry: 'Pinaka Rockets & Drones', type: 'stock', capTier: 'LARGE', lotSize: 100, isFO: true, aliases: ['solar industries', 'pinaka rockets', 'explosives'] },

  // Green Energy, Power & Utilities
  { symbol: 'SUZLON', name: 'Suzlon Energy Ltd', sector: 'Renewable & Wind Energy', subIndustry: 'Wind Turbines (WTG)', type: 'stock', capTier: 'MID', lotSize: 7500, isFO: true, aliases: ['wind turbine', 'green energy', 'suzlon'] },
  { symbol: 'INOXWIND', name: 'Inox Wind Ltd', sector: 'Renewable & Wind Energy', subIndustry: 'Wind Turbine Generator Systems', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['inox wind', 'wind energy'] },
  { symbol: 'IREDA', name: 'Indian Renewable Energy Development Agency', sector: 'Green Energy Financing', subIndustry: 'Solar & Wind Project Loans', type: 'stock', capTier: 'MID', lotSize: 2400, isFO: true, aliases: ['solar financing', 'green nbfc', 'ireda'] },
  { symbol: 'PFC', name: 'Power Finance Corporation Ltd', sector: 'Power NBFC', subIndustry: 'Power Infrastructure Financing', type: 'stock', capTier: 'LARGE', lotSize: 1300, isFO: true, aliases: ['power finance', 'pfc'] },
  { symbol: 'RECLTD', name: 'REC Ltd', sector: 'Power NBFC', subIndustry: 'Rural Electrification & Renewables', type: 'stock', capTier: 'LARGE', lotSize: 1400, isFO: true, aliases: ['rural electrification', 'rec'] },
  { symbol: 'TATAPOWER', name: 'Tata Power Company Ltd', sector: 'Power & Solar Rooftop', subIndustry: 'Generation, Solar & EV Charging', type: 'stock', capTier: 'LARGE', lotSize: 1350, isFO: true, aliases: ['tata power', 'ev charging', 'solar rooftop'] },
  { symbol: 'ADANIGREEN', name: 'Adani Green Energy Ltd', sector: 'Renewable Energy', subIndustry: 'Khavda Mega Solar & Wind Parks', type: 'stock', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['adani green', 'solar park'] },
  { symbol: 'ADANIPOWER', name: 'Adani Power Ltd', sector: 'Thermal Power', subIndustry: 'Merchant Power Generation', type: 'stock', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['adani power', 'thermal'] },
  { symbol: 'NHPC', name: 'NHPC Ltd', sector: 'Hydro Power', subIndustry: 'Hydropower Generation', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['hydro', 'nhpc'] },
  { symbol: 'TORNTPOWER', name: 'Torrent Power Ltd', sector: 'Power & Discom', subIndustry: 'Generation & Distribution', type: 'stock', capTier: 'MID', lotSize: 375, isFO: true, aliases: ['torrent power'] },
  { symbol: 'CGPOWER', name: 'CG Power and Industrial Solutions Ltd', sector: 'Capital Goods & Motors', subIndustry: 'Transformers, Motors & OSAT Semi', type: 'stock', capTier: 'LARGE', lotSize: 850, isFO: true, aliases: ['cg power', 'murugappa', 'semiconductor'] },
  { symbol: 'BHEL', name: 'Bharat Heavy Electricals Ltd', sector: 'Heavy Electrical Equipment', subIndustry: 'Thermal Turbines & Locomotives', type: 'stock', capTier: 'LARGE', lotSize: 2625, isFO: true, aliases: ['bhel', 'turbines', 'power equipment'] },

  // Railways & Infrastructure
  { symbol: 'RVNL', name: 'Rail Vikas Nigam Ltd', sector: 'Railway Infrastructure', subIndustry: 'Vande Bharat & Rail Track Laying', type: 'stock', capTier: 'MID', lotSize: 1750, isFO: true, aliases: ['railway', 'vande bharat', 'rail vikas', 'rvnl'] },
  { symbol: 'IRFC', name: 'Indian Railway Finance Corporation', sector: 'Railway NBFC', subIndustry: 'Rolling Stock Financing', type: 'stock', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['irfc', 'railway finance'] },
  { symbol: 'IRCTC', name: 'Indian Railway Catering and Tourism Corp', sector: 'Rail Travel & Catering', subIndustry: 'Train Ticketing & Catering Monopoly', type: 'stock', capTier: 'MID', lotSize: 625, isFO: true, aliases: ['irctc', 'rail ticketing', 'catering'] },
  { symbol: 'TITAGARH', name: 'Titagarh Rail Systems Ltd', sector: 'Railway Wagons & Metros', subIndustry: 'Vande Bharat Coaches & Freight Wagons', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['titagarh', 'rail wagons', 'metro coaches'] },
  { symbol: 'JUPITERWAG', name: 'Jupiter Wagons Ltd', sector: 'Railway Freight & EV', subIndustry: 'Railway Wagons & Braking Systems', type: 'stock', capTier: 'SMALL', lotSize: null, isFO: false, aliases: ['jupiter wagons', 'freight wagons'] },
  { symbol: 'RAILTEL', name: 'RailTel Corporation of India Ltd', sector: 'Telecom & Rail Infra', subIndustry: 'Optic Fiber & Station Wi-Fi', type: 'stock', capTier: 'SMALL', lotSize: null, isFO: false, aliases: ['railtel', 'rail telecom'] },

  // Real Estate & Construction
  { symbol: 'DLF', name: 'DLF Ltd', sector: 'Realty & Luxury Housing', subIndustry: 'Gurgaon Luxury & Commercial Leases', type: 'stock', capTier: 'LARGE', lotSize: 825, isFO: true, aliases: ['dlf', 'gurgaon luxury', 'real estate', 'camilia'] },
  { symbol: 'GODREJPROP', name: 'Godrej Properties Ltd', sector: 'Realty & Residential', subIndustry: 'Pan-India Premium Housing', type: 'stock', capTier: 'MID', lotSize: 225, isFO: true, aliases: ['godrej', 'real estate', 'godrej properties'] },
  { symbol: 'OBEROIRLTY', name: 'Oberoi Realty Ltd', sector: 'Realty & Mumbai Luxury', subIndustry: 'Mumbai High-End Developments', type: 'stock', capTier: 'MID', lotSize: 350, isFO: true, aliases: ['oberoi', 'mumbai residential', 'luxury flats'] },
  { symbol: 'PRESTIGE', name: 'Prestige Estates Projects Ltd', sector: 'Realty & South India', subIndustry: 'Bengaluru & Mumbai High-Rises', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['prestige', 'real estate'] },
  { symbol: 'PHOENIXLTD', name: 'The Phoenix Mills Ltd', sector: 'Commercial Malls & Leases', subIndustry: 'Premium Shopping Malls', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['phoenix mall', 'malls'] },

  // Banking & Financial Midcaps
  { symbol: 'FEDERALBNK', name: 'The Federal Bank Ltd', sector: 'Private Banking', subIndustry: 'South India & Fintech Partnerships', type: 'stock', capTier: 'MID', lotSize: 5000, isFO: true, aliases: ['federal bank', 'fintech bank'] },
  { symbol: 'IDFCFIRSTB', name: 'IDFC First Bank Ltd', sector: 'Private Banking', subIndustry: 'Retail CASA & Digital Lending', type: 'stock', capTier: 'MID', lotSize: 7500, isFO: true, aliases: ['idfc bank', 'vaidyanathan', 'idfc first'] },
  { symbol: 'AUBANK', name: 'AU Small Finance Bank Ltd', sector: 'Small Finance Banking', subIndustry: 'Retail High-Growth SFB', type: 'stock', capTier: 'MID', lotSize: 1000, isFO: true, aliases: ['au bank', 'au small finance'] },
  { symbol: 'BANKBARODA', name: 'Bank of Baroda', sector: 'PSU Banking', subIndustry: 'Tier-1 PSU Banking', type: 'stock', capTier: 'LARGE', lotSize: 2925, isFO: true, aliases: ['bob', 'bank of baroda'] },
  { symbol: 'PNB', name: 'Punjab National Bank', sector: 'PSU Banking', subIndustry: 'Tier-1 PSU Banking', type: 'stock', capTier: 'LARGE', lotSize: 4000, isFO: true, aliases: ['pnb', 'punjab national bank'] },
  { symbol: 'CANBK', name: 'Canara Bank', sector: 'PSU Banking', subIndustry: 'PSU Banking & Can Fin', type: 'stock', capTier: 'LARGE', lotSize: 3375, isFO: true, aliases: ['canara bank', 'canbk'] },
  { symbol: 'UNIONBANK', name: 'Union Bank of India', sector: 'PSU Banking', subIndustry: 'PSU Banking', type: 'stock', capTier: 'LARGE', lotSize: 4250, isFO: true, aliases: ['union bank', 'ubi'] },
  { symbol: 'CHOLAFIN', name: 'Cholamandalam Investment & Finance', sector: 'Vehicle NBFC', subIndustry: 'Commercial Vehicle & Home Equity', type: 'stock', capTier: 'LARGE', lotSize: 500, isFO: true, aliases: ['murugappa', 'chola', 'cholamandalam'] },
  { symbol: 'MUTHOOTFIN', name: 'Muthoot Finance Ltd', sector: 'Gold Loans NBFC', subIndustry: 'Secured Gold Jewellery Lending', type: 'stock', capTier: 'LARGE', lotSize: 350, isFO: true, aliases: ['gold loan', 'muthoot', 'gold financing'] },

  // Healthcare & Diagnostics
  { symbol: 'MAXHEALTH', name: 'Max Healthcare Institute Ltd', sector: 'Hospitals & Healthcare', subIndustry: 'Super-Specialty Hospital Chain', type: 'stock', capTier: 'LARGE', lotSize: 525, isFO: true, aliases: ['max hospital', 'super specialty', 'max healthcare'] },
  { symbol: 'FORTIS', name: 'Fortis Healthcare Ltd', sector: 'Hospitals & Healthcare', subIndustry: 'IHH Healthcare Hospital Network', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['fortis', 'ihh'] },
  { symbol: 'MEDANTA', name: 'Global Health Ltd (Medanta)', sector: 'Hospitals & Healthcare', subIndustry: 'Cardiac & Multi-Organ Transplants', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['medanta', 'dr trehan'] },
  { symbol: 'LUPIN', name: 'Lupin Ltd', sector: 'Pharma & Inhalation', subIndustry: 'Generics & Respiratory', type: 'stock', capTier: 'LARGE', lotSize: 425, isFO: true, aliases: ['lupin', 'respiratory'] },
  { symbol: 'ZYDUSLIFE', name: 'Zydus Lifesciences Ltd', sector: 'Pharma & Injectables', subIndustry: 'Biosimilars & US Generics', type: 'stock', capTier: 'LARGE', lotSize: 900, isFO: true, aliases: ['zydus', 'cadila'] },
  { symbol: 'TORNTPHARM', name: 'Torrent Pharmaceuticals Ltd', sector: 'Pharma & Chronic', subIndustry: 'Cardiovascular & CNS Therapies', type: 'stock', capTier: 'LARGE', lotSize: 250, isFO: true, aliases: ['torrent pharma'] },
  { symbol: 'MANKIND', name: 'Mankind Pharma Ltd', sector: 'Pharma & OTC', subIndustry: 'Domestic Formulations & Manforce', type: 'stock', capTier: 'LARGE', lotSize: 250, isFO: true, aliases: ['mankind', 'prega news', 'gas-o-fast'] },
  { symbol: 'AUROPHARMA', name: 'Aurobindo Pharma Ltd', sector: 'Pharma & Injectables', subIndustry: 'Oral Solides & Sterile Injectables', type: 'stock', capTier: 'LARGE', lotSize: 550, isFO: true, aliases: ['aurobindo', 'auro pharma'] },
  { symbol: 'BIOCON', name: 'Biocon Ltd', sector: 'Biopharma & Biosimilars', subIndustry: 'Insulins & Monoclonal Antibodies', type: 'stock', capTier: 'MID', lotSize: 2500, isFO: true, aliases: ['biocon', 'kiran mazumdar shaw', 'biosimilars'] },

  // Consumer, QSR & Retail
  { symbol: 'VBL', name: 'Varun Beverages Ltd', sector: 'Beverages & Bottling', subIndustry: 'PepsiCo Bottler & Sting Energy', type: 'stock', capTier: 'LARGE', lotSize: 500, isFO: true, aliases: ['pepsico', 'sting', 'varun', 'mountain dew'] },
  { symbol: 'DMART', name: 'Avenue Supermarts Ltd (DMart)', sector: 'Retail & Hypermarkets', subIndustry: 'Everyday Low Price Groceries', type: 'stock', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['dmart', 'radhakishan damani', 'supermarket'] },
  { symbol: 'SWIGGY', name: 'Swiggy Ltd (Instamart)', sector: 'Quick Commerce & Food', subIndustry: 'Q-Commerce & Dineout', type: 'stock', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['swiggy', 'instamart', 'dineout', 'food delivery'] },
  { symbol: 'KALYANKJIL', name: 'Kalyan Jewellers India Ltd', sector: 'Jewellery Retail', subIndustry: 'Pan-India Showrooms & Candere', type: 'stock', capTier: 'MID', lotSize: 1200, isFO: true, aliases: ['kalyan', 'candere', 'gold jewellery'] },
  { symbol: 'JUBLFOOD', name: 'Jubilant FoodWorks Ltd', sector: 'QSR & Fast Food', subIndustry: 'Dominos Pizza & Popeyes', type: 'stock', capTier: 'MID', lotSize: 1250, isFO: true, aliases: ['dominos', 'pizza', 'jubilant', 'dunkin'] },
  { symbol: 'DEVYANI', name: 'Devyani International Ltd', sector: 'QSR & Fast Food', subIndustry: 'KFC, Pizza Hut & Costa Coffee', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['kfc', 'pizza hut', 'costa coffee', 'devyani'] },
  { symbol: 'DABUR', name: 'Dabur India Ltd', sector: 'FMCG & Ayurveda', subIndustry: 'Chyawanprash, Real Juice & Vatika', type: 'stock', capTier: 'LARGE', lotSize: 1250, isFO: true, aliases: ['dabur', 'ayurveda', 'real juice'] },
  { symbol: 'MARICO', name: 'Marico Ltd', sector: 'FMCG & Edible Oils', subIndustry: 'Parachute Coconut Oil & Saffola', type: 'stock', capTier: 'LARGE', lotSize: 1200, isFO: true, aliases: ['marico', 'parachute', 'saffola'] },
  { symbol: 'GODREJCP', name: 'Godrej Consumer Products Ltd', sector: 'FMCG & Household', subIndustry: 'Goodknight, HIT & Cinthol', type: 'stock', capTier: 'LARGE', lotSize: 500, isFO: true, aliases: ['godrej consumer', 'goodknight', 'cinthol'] },
  { symbol: 'COLPAL', name: 'Colgate-Palmolive (India) Ltd', sector: 'FMCG & Oral Care', subIndustry: 'Colgate Toothpaste Monopoly', type: 'stock', capTier: 'LARGE', lotSize: 200, isFO: true, aliases: ['colgate', 'toothpaste', 'oral care'] },
  { symbol: 'PAGEIND', name: 'Page Industries Ltd (Jockey)', sector: 'Apparel & Innerwear', subIndustry: 'Jockey & Speedo Licensee', type: 'stock', capTier: 'MID', lotSize: 15, isFO: true, aliases: ['jockey', 'page industries', 'innerwear'] },

  // Mobility, 2W & Auto Ancillaries
  { symbol: 'TVSMOTOR', name: 'TVS Motor Company Ltd', sector: '2-Wheelers & EV', subIndustry: 'iQube EV, Apache & Norton', type: 'stock', capTier: 'LARGE', lotSize: 250, isFO: true, aliases: ['tvs', 'tvs iqube', 'tvs apache', '2-wheeler'] },
  { symbol: 'ASHOKLEY', name: 'Ashok Leyland Ltd', sector: 'Commercial Vehicles & EV', subIndustry: 'Medium & Heavy Trucks, Switch EV', type: 'stock', capTier: 'MID', lotSize: 3500, isFO: true, aliases: ['hinduja', 'trucks', 'switch mobility', 'ashok leyland'] },
  { symbol: 'BHARATFORG', name: 'Bharat Forge Ltd', sector: 'Forging & Defense', subIndustry: 'Automotive Forgings & ATAGS Artillery', type: 'stock', capTier: 'LARGE', lotSize: 500, isFO: true, aliases: ['bharat forge', 'kalyani', 'artillery guns', 'forging'] },
  { symbol: 'MOTHERSON', name: 'Samvardhana Motherson International Ltd', sector: 'Auto Ancillary & Wiring', subIndustry: 'Wiring Harnesses & Vision Systems', type: 'stock', capTier: 'LARGE', lotSize: 4400, isFO: true, aliases: ['motherson sumi', 'wiring harness'] },
  { symbol: 'SONACOMS', name: 'Sona BLW Precision Forgings Ltd', sector: 'EV Components', subIndustry: 'Differential Gears & Traction Motors', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['sona coms', 'ev gears'] },
  { symbol: 'EXIDEIND', name: 'Exide Industries Ltd', sector: 'Auto Batteries & Lithium Cells', subIndustry: 'Lead Acid & Lithium Gigafactory', type: 'stock', capTier: 'MID', lotSize: 1200, isFO: true, aliases: ['exide', 'batteries', 'lithium cell', 'hyundai kia tieup'] },
  { symbol: 'MRF', name: 'MRF Ltd', sector: 'Tyres & Rubber', subIndustry: 'Tyre Market Leader', type: 'stock', capTier: 'LARGE', lotSize: 5, isFO: true, aliases: ['mrf', 'tyres', 'mrf tyre'] },
  { symbol: 'APOLLOTYRE', name: 'Apollo Tyres Ltd', sector: 'Tyres & Rubber', subIndustry: 'Vredestein & Truck Tyres', type: 'stock', capTier: 'MID', lotSize: 1700, isFO: true, aliases: ['apollo tyres', 'vredestein'] },
  { symbol: 'BALKRISIND', name: 'Balkrishna Industries Ltd (BKT)', sector: 'Off-Highway Tyres', subIndustry: 'Agricultural & Mining Tyres', type: 'stock', capTier: 'MID', lotSize: 200, isFO: true, aliases: ['bkt', 'balkrishna', 'off-highway tyres'] },
  { symbol: 'BOSCHLTD', name: 'Bosch Ltd', sector: 'Auto Tech & Powertrain', subIndustry: 'Common Rail & EV Powertrains', type: 'stock', capTier: 'LARGE', lotSize: 25, isFO: true, aliases: ['bosch', 'german engineering'] },

  // Consumer Durables, AC & Cables
  { symbol: 'VOLTAS', name: 'Voltas Ltd', sector: 'AC & Consumer Durables', subIndustry: 'Room Air Conditioners & Beko', type: 'stock', capTier: 'MID', lotSize: 375, isFO: true, aliases: ['voltas', 'tata ac', 'cooling', 'air conditioner'] },
  { symbol: 'HAVELLS', name: 'Havells India Ltd (Lloyd)', sector: 'Electrical Goods & Lloyd', subIndustry: 'Switchgear, Fans, Cables & AC', type: 'stock', capTier: 'LARGE', lotSize: 350, isFO: true, aliases: ['havells', 'lloyd', 'switchgear', 'fans'] },
  { symbol: 'CROMPTON', name: 'Crompton Greaves Consumer Electricals', sector: 'Consumer Electricals', subIndustry: 'Fans, Lighting & Butterfly Appliances', type: 'stock', capTier: 'MID', lotSize: 1800, isFO: true, aliases: ['crompton', 'fans', 'appliances'] },

  // Specialty Chemicals & Fertilizers
  { symbol: 'PIIND', name: 'PI Industries Ltd', sector: 'Agrochemicals & CSM', subIndustry: 'Custom Synthesis & Nominee Gold', type: 'stock', capTier: 'LARGE', lotSize: 250, isFO: true, aliases: ['pi ind', 'csm', 'agrochemicals'] },
  { symbol: 'SRF', name: 'SRF Ltd', sector: 'Specialty Chemicals & Packaging', subIndustry: 'Fluorochemicals & Technical Textiles', type: 'stock', capTier: 'LARGE', lotSize: 375, isFO: true, aliases: ['srf', 'fluorochemicals', 'refrigerants'] },
  { symbol: 'NAVINFLUOR', name: 'Navin Fluorine International Ltd', sector: 'Specialty Fluorochemicals', subIndustry: 'HPP & CDMO Inhalation', type: 'stock', capTier: 'MID', lotSize: 175, isFO: true, aliases: ['navin fluorine', 'fluorine'] },
  { symbol: 'DEEPAKNTR', name: 'Deepak Nitrite Ltd', sector: 'Basic & Specialty Chemicals', subIndustry: 'Phenol, Acetone & Nitration', type: 'stock', capTier: 'MID', lotSize: 300, isFO: true, aliases: ['deepak nitrite', 'phenol'] },
  { symbol: 'ATUL', name: 'Atul Ltd', sector: 'Specialty Chemicals & Polymers', subIndustry: 'Aromatics & Epoxy Resins', type: 'stock', capTier: 'MID', lotSize: 75, isFO: true, aliases: ['atul', 'dyes', 'polymers'] },
  { symbol: 'COROMANDEL', name: 'Coromandel International Ltd', sector: 'Fertilizers & Agrochemicals', subIndustry: 'Phosphatic Fertilizers (Murugappa)', type: 'stock', capTier: 'LARGE', lotSize: 700, isFO: true, aliases: ['coromandel', 'fertilizers', 'gromor'] },
  { symbol: 'UPL', name: 'UPL Ltd', sector: 'Crop Protection & Seeds', subIndustry: 'Post-Patent Agrochemicals', type: 'stock', capTier: 'MID', lotSize: 1300, isFO: true, aliases: ['upl', 'agrochemicals'] },
  { symbol: 'TATACHEM', name: 'Tata Chemicals Ltd', sector: 'Inorganic Chemicals', subIndustry: 'Soda Ash & Sodium Bicarbonate', type: 'stock', capTier: 'MID', lotSize: 550, isFO: true, aliases: ['tata chem', 'soda ash'] },

  // Metals & Mining
  { symbol: 'JINDALSTEL', name: 'Jindal Steel & Power Ltd', sector: 'Metals & Steel', subIndustry: 'Plates, Rails & Pellets', type: 'stock', capTier: 'LARGE', lotSize: 625, isFO: true, aliases: ['jspl', 'jindal steel', 'naveen jindal'] },
  { symbol: 'NMDC', name: 'NMDC Ltd', sector: 'Mining & Iron Ore', subIndustry: 'Iron Ore Merchant Mining', type: 'stock', capTier: 'LARGE', lotSize: 4500, isFO: true, aliases: ['nmdc', 'iron ore', 'bailadila'] },
  { symbol: 'SAIL', name: 'Steel Authority of India Ltd', sector: 'PSU Steel', subIndustry: 'Bhilai & Bokaro Integrated Plants', type: 'stock', capTier: 'MID', lotSize: 8000, isFO: true, aliases: ['sail', 'steel authority', 'psu steel'] },
  { symbol: 'VEDL', name: 'Vedanta Ltd', sector: 'Metals & Diversified Natural Resources', subIndustry: 'Zinc, Aluminium, Oil & Power', type: 'stock', capTier: 'LARGE', lotSize: 1150, isFO: true, aliases: ['vedanta', 'anil agarwal', 'dividend yield'] },
  { symbol: 'NATIONALUM', name: 'National Aluminium Company Ltd', sector: 'PSU Aluminium & Bauxite', subIndustry: 'Low-Cost Alumina Smelting', type: 'stock', capTier: 'MID', lotSize: 3750, isFO: true, aliases: ['nalco', 'nationalum', 'aluminium'] },
  { symbol: 'HINDZINC', name: 'Hindustan Zinc Ltd', sector: 'Zinc, Lead & Silver', subIndustry: 'World Top Zinc & Silver Miner', type: 'stock', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['hindustan zinc', 'silver mining', 'zinc'] },
  { symbol: 'APLAPOLLO', name: 'APL Apollo Tubes Ltd', sector: 'Structural Steel Tubes', subIndustry: 'Hollow Sections & Roofing Tubes', type: 'stock', capTier: 'MID', lotSize: 700, isFO: true, aliases: ['apl apollo', 'steel tubes'] },
  { symbol: 'HINDCOPPER', name: 'Hindustan Copper Ltd', sector: 'Copper Mining & Smelting', subIndustry: 'Primary Copper Ore Refining', type: 'stock', capTier: 'MID', lotSize: 2650, isFO: true, aliases: ['hindustan copper', 'copper mining'] },
  { symbol: 'RATNAMANI', name: 'Ratnamani Metals & Tubes Ltd', sector: 'Process Pipes & Tubes', subIndustry: 'Stainless & Carbon Steel Pipes', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['ratnamani', 'pipes'] },

  // Aviation, Logistics & Media
  { symbol: 'INDIGO', name: 'InterGlobe Aviation Ltd (IndiGo)', sector: 'Aviation & Airlines', subIndustry: 'Low-Cost Carrier Monopoly', type: 'stock', capTier: 'LARGE', lotSize: 300, isFO: true, aliases: ['indigo', 'interglobe', 'airlines', 'aviation'] },
  { symbol: 'CONCOR', name: 'Container Corporation of India Ltd', sector: 'Rail Freight & Logistics', subIndustry: 'Inland Container Depots (ICD)', type: 'stock', capTier: 'MID', lotSize: 1000, isFO: true, aliases: ['concor', 'container logistics'] },
  { symbol: 'DELHIVERY', name: 'Delhivery Ltd', sector: 'E-Commerce Logistics & Express', subIndustry: 'Automated Sortation Hubs', type: 'stock', capTier: 'MID', lotSize: null, isFO: false, aliases: ['delhivery', 'courier', 'logistics'] },
  { symbol: 'PVRINOX', name: 'PVR INOX Ltd', sector: 'Multiplex Cinema Exhibition', subIndustry: 'Cinema Screens & F&B', type: 'stock', capTier: 'MID', lotSize: 400, isFO: true, aliases: ['pvr', 'inox', 'multiplex', 'movies'] },
  { symbol: 'SUNTV', name: 'Sun TV Network Ltd', sector: 'Media & Broadcasting', subIndustry: 'South Indian Regional Channels & IPL', type: 'stock', capTier: 'MID', lotSize: 1500, isFO: true, aliases: ['sun tv', 'maran', 'sunrisers'] },
  { symbol: 'ZEEL', name: 'Zee Entertainment Enterprises Ltd', sector: 'Media & OTT', subIndustry: 'Zee5 & Satellite Broadcasting', type: 'stock', capTier: 'MID', lotSize: 3000, isFO: true, aliases: ['zee', 'zeel', 'zee5'] },

  // ─────────────────────────────────────────────────────────────
  // 4. LEADING INDIAN ETFS (EXCHANGE TRADED FUNDS)
  // ─────────────────────────────────────────────────────────────
  { symbol: 'NIFTYBEES', name: 'Nippon India ETF Nifty 50 BeES', sector: 'ETF', subIndustry: 'Nifty 50 Index ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['nifty bees', 'niftybees', 'nifty etf', 'index fund'] },
  { symbol: 'BANKBEES', name: 'Nippon India ETF Bank BeES', sector: 'ETF', subIndustry: 'Bank Nifty Index ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['bank bees', 'bankbees', 'bank etf'] },
  { symbol: 'GOLDBEES', name: 'Nippon India ETF Gold BeES', sector: 'ETF', subIndustry: 'Physical Gold Backed ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['gold bees', 'goldbees', 'gold etf', 'physical gold', 'sona'] },
  { symbol: 'SILVERBEES', name: 'Nippon India ETF Silver BeES', sector: 'ETF', subIndustry: 'Physical Silver Backed ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['silver bees', 'silverbees', 'silver etf', 'chandi'] },
  { symbol: 'ITBEES', name: 'Nippon India ETF Nifty IT', sector: 'ETF', subIndustry: 'Nifty IT Sector ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['it bees', 'itbees', 'tech etf'] },
  { symbol: 'AUTOBEES', name: 'Nippon India ETF Nifty Auto', sector: 'ETF', subIndustry: 'Nifty Auto Sector ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['auto bees', 'autobees', 'auto etf'] },
  { symbol: 'PHARMABEES', name: 'Nippon India ETF Nifty Pharma', sector: 'ETF', subIndustry: 'Pharma Sector ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['pharma bees', 'pharmabees', 'pharma etf'] },
  { symbol: 'JUNIORBEES', name: 'Nippon India ETF Junior BeES', sector: 'ETF', subIndustry: 'Nifty Next 50 ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['junior bees', 'juniorbees', 'next 50 etf'] },
  { symbol: 'MID150BEES', name: 'Nippon India ETF Nifty Midcap 150', sector: 'ETF', subIndustry: 'Midcap 150 Index ETF', type: 'etf', capTier: 'MID', lotSize: null, isFO: false, aliases: ['midcap bees', 'mid150bees', 'midcap etf'] },
  { symbol: 'CPSEETF', name: 'CPSE ETF (PSU Maharatna & Navratna)', sector: 'ETF', subIndustry: 'Central Public Sector Enterprises', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['cpse', 'cpse etf', 'psu etf'] },
  { symbol: 'BHARAT22', name: 'ICICI Prudential Bharat 22 ETF', sector: 'ETF', subIndustry: 'Government Disinvestment Index', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['bharat 22', 'bharat22', 'disinvestment etf'] },
  { symbol: 'MON100', name: 'Motilal Oswal Nasdaq 100 ETF', sector: 'ETF', subIndustry: 'US Tech & Nasdaq 100 in INR', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['nasdaq', 'nasdaq etf', 'mon100', 'us tech', 'apple', 'nvidia'] },
  { symbol: 'MAFANG', name: 'Mirae Asset NYSE FANG+ ETF', sector: 'ETF', subIndustry: 'US Mega-Cap Tech (Meta, Apple, Google, Nvidia)', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['fang', 'fang etf', 'mafang', 'magnificent seven'] },
  { symbol: 'LIQUIDBEES', name: 'Nippon India ETF Liquid BeES', sector: 'ETF', subIndustry: 'Daily Dividend Cash Yield ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['liquid bees', 'liquidbees', 'cash park', 'margin collateral'] },
  { symbol: 'HDFCGOLD', name: 'HDFC Gold ETF', sector: 'ETF', subIndustry: 'Gold Bullion ETF', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['hdfc gold', 'gold etf'] },
  { symbol: 'SETFNIF50', name: 'SBI Nifty 50 ETF (EPFO Investment)', sector: 'ETF', subIndustry: 'Nifty 50 Index Tracker', type: 'etf', capTier: 'LARGE', lotSize: null, isFO: false, aliases: ['sbi nifty etf', 'setfnif50'] },

  // ─────────────────────────────────────────────────────────────
  // 5. MCX COMMODITIES DERIVATIVES
  // ─────────────────────────────────────────────────────────────
  { symbol: 'GOLD', name: 'MCX Gold Futures (1kg / 10g Base)', sector: 'Commodities', subIndustry: 'Precious Metals', type: 'commodity', capTier: 'LARGE', lotSize: 1, isFO: true, aliases: ['gold', 'mcx gold', 'sona', 'bullion', 'yellow metal'] },
  { symbol: 'GOLDM', name: 'MCX Gold Mini Futures (100g)', sector: 'Commodities', subIndustry: 'Precious Metals Mini', type: 'commodity', capTier: 'LARGE', lotSize: 1, isFO: true, aliases: ['gold mini', 'goldm', 'mini gold'] },
  { symbol: 'GOLDPETAL', name: 'MCX Gold Petal (1g Contract)', sector: 'Commodities', subIndustry: 'Micro Gold', type: 'commodity', capTier: 'SMALL', lotSize: 1, isFO: true, aliases: ['gold petal', '1g gold'] },
  { symbol: 'SILVER', name: 'MCX Silver Futures (30kg Contract)', sector: 'Commodities', subIndustry: 'Industrial & Precious Metals', type: 'commodity', capTier: 'LARGE', lotSize: 1, isFO: true, aliases: ['silver', 'mcx silver', 'chandi', 'white metal'] },
  { symbol: 'SILVERM', name: 'MCX Silver Mini Futures (5kg)', sector: 'Commodities', subIndustry: 'Silver Mini', type: 'commodity', capTier: 'LARGE', lotSize: 1, isFO: true, aliases: ['silver mini', 'silverm'] },
  { symbol: 'SILVERMIC', name: 'MCX Silver Micro Futures (1kg)', sector: 'Commodities', subIndustry: 'Silver Micro', type: 'commodity', capTier: 'SMALL', lotSize: 1, isFO: true, aliases: ['silver micro', 'silvermic'] },
  { symbol: 'CRUDEOIL', name: 'MCX WTI/Brent Crude Oil Futures (100 bbl)', sector: 'Commodities', subIndustry: 'Energy & Petroleum', type: 'commodity', capTier: 'LARGE', lotSize: 100, isFO: true, aliases: ['crude', 'crude oil', 'mcx crude', 'petroleum', 'wti', 'brent'] },
  { symbol: 'CRUDEOILM', name: 'MCX Crude Oil Mini Futures (10 bbl)', sector: 'Commodities', subIndustry: 'Energy Mini', type: 'commodity', capTier: 'LARGE', lotSize: 10, isFO: true, aliases: ['crude mini', 'crudeoilm'] },
  { symbol: 'NATURALGAS', name: 'MCX Natural Gas Futures (1250 mmBtu)', sector: 'Commodities', subIndustry: 'Energy & Heating Gas', type: 'commodity', capTier: 'LARGE', lotSize: 1250, isFO: true, aliases: ['nat gas', 'natural gas', 'mcx gas', 'henry hub'] },
  { symbol: 'NATGASMINI', name: 'MCX Natural Gas Mini (250 mmBtu)', sector: 'Commodities', subIndustry: 'Natural Gas Mini', type: 'commodity', capTier: 'MID', lotSize: 250, isFO: true, aliases: ['nat gas mini', 'natgasmini'] },
  { symbol: 'COPPER', name: 'MCX Copper High Grade Futures (2500 kg)', sector: 'Commodities', subIndustry: 'Base Metals & Electrification', type: 'commodity', capTier: 'LARGE', lotSize: 2500, isFO: true, aliases: ['copper', 'mcx copper', 'tamba', 'red metal'] },
  { symbol: 'ZINC', name: 'MCX Zinc Futures (5000 kg)', sector: 'Commodities', subIndustry: 'Base Metals Galvanization', type: 'commodity', capTier: 'LARGE', lotSize: 5000, isFO: true, aliases: ['zinc', 'mcx zinc', 'jasta'] },
  { symbol: 'ALUMINIUM', name: 'MCX Aluminium Futures (5000 kg)', sector: 'Commodities', subIndustry: 'Lightweight Base Metals', type: 'commodity', capTier: 'LARGE', lotSize: 5000, isFO: true, aliases: ['aluminium', 'mcx aluminium', 'aluminum'] },
  { symbol: 'LEAD', name: 'MCX Lead Futures (5000 kg)', sector: 'Commodities', subIndustry: 'Battery Heavy Metals', type: 'commodity', capTier: 'LARGE', lotSize: 5000, isFO: true, aliases: ['lead', 'mcx lead', 'seesa'] },
  { symbol: 'COTTON', name: 'MCX Cotton Candy (25 Bales)', sector: 'Commodities', subIndustry: 'Agri Commodity', type: 'commodity', capTier: 'MID', lotSize: 25, isFO: true, aliases: ['cotton', 'mcx cotton', 'kapas'] },

  // ─────────────────────────────────────────────────────────────
  // 6. CURRENCY DERIVATIVES (CDS)
  // ─────────────────────────────────────────────────────────────
  { symbol: 'USDINR', name: 'US Dollar / Indian Rupee (USD/INR)', sector: 'Forex & Currencies', subIndustry: 'Major Currency Pair', type: 'currency', capTier: 'LARGE', lotSize: 1000, isFO: true, aliases: ['usdinr', 'dollar', 'usd', 'forex', 'rupee dollar'] },
  { symbol: 'EURINR', name: 'Euro / Indian Rupee (EUR/INR)', sector: 'Forex & Currencies', subIndustry: 'European Currency Pair', type: 'currency', capTier: 'LARGE', lotSize: 1000, isFO: true, aliases: ['eurinr', 'euro', 'eur'] },
  { symbol: 'GBPINR', name: 'British Pound / Indian Rupee (GBP/INR)', sector: 'Forex & Currencies', subIndustry: 'Sterling Currency Pair', type: 'currency', capTier: 'LARGE', lotSize: 1000, isFO: true, aliases: ['gbpinr', 'pound', 'gbp', 'sterling'] },
  { symbol: 'JPYINR', name: 'Japanese Yen / 100 Indian Rupee (JPY/INR)', sector: 'Forex & Currencies', subIndustry: 'Asian FX Pair', type: 'currency', capTier: 'LARGE', lotSize: 1000, isFO: true, aliases: ['jpyinr', 'yen', 'jpy'] },
]

export const COUNCIL_REGISTRY = [
  { id: 'breakout', name: 'Breakout Momentum Council', icon: '🚀', members: ['minervini', 'wyckoff', 'oneil', 'forensic'], desc: 'SEPA VCP setups, CAN SLIM volume confirmation, and forensic quality audit.' },
  { id: 'options_sniper', name: 'Options Sniper Council', icon: '🎯', members: ['smc', 'taleb', 'simons'], desc: 'ICT order block sweeps, defined-risk asymmetry, and statistical arbitrage.' },
  { id: 'multibagger', name: 'Multibagger Compounder Council', icon: '💎', members: ['kedia', 'buffett', 'munger', 'jhunjhunwala', 'forensic'], desc: 'SMILE framework, durable business moats, and forensic integrity.' },
  { id: 'macro_regime', name: 'Macro & Flow Regime Council', icon: '🌐', members: ['soros', 'jhunjhunwala', 'simons', 'forensic'], desc: 'Global liquidity, FII/DII institutional positioning, and cross-asset reflexivity.' },
  { id: 'core_value', name: 'Core Value & Quality Council', icon: '🏛️', members: ['buffett', 'munger', 'lynch', 'forensic'], desc: 'High ROE, conservative debt, earnings consistency, and margin of safety.' },
]

export const PERSONA_REGISTRY = [
  { id: 'minervini', name: 'Mark Minervini', icon: '🚀', style: 'SEPA / VCP Breakout Specialist', desc: '8-point Trend Template, Volatility Contraction, and strict loss cutting.' },
  { id: 'kedia', name: 'Vijay Kedia', icon: '💎', style: 'SMILE Multibagger Framework', desc: 'Small size, Market potential, Investment in management, Large earnings growth.' },
  { id: 'jhunjhunwala', name: 'Rakesh Jhunjhunwala', icon: '🐂', style: 'Indian Growth & Moats', desc: 'Demographic tailwinds, structural consumption growth, and conviction holding.' },
  { id: 'buffett', name: 'Warren Buffett', icon: '🏛️', style: 'Deep Value & Moat Quality', desc: 'Durable competitive advantages, high ROE, owner earnings, and margin of safety.' },
  { id: 'munger', name: 'Charlie Munger', icon: '🧠', style: 'Quality Compounders & Inversion', desc: 'Moat preservation, mental models, and avoiding institutional stupidity.' },
  { id: 'lynch', name: 'Peter Lynch', icon: '🛍️', style: 'GARP & Fast Growers', desc: 'PEG ratio, fast growing smallcaps, and bottom-up consumer insights.' },
  { id: 'taleb', name: 'Nassim Taleb', icon: '🛡️', style: 'Defined-Risk Convexity & Tail Risk', desc: 'Antifragility, strictly capped downside, and unhedged explosive upside.' },
  { id: 'soros', name: 'George Soros', icon: '🌐', style: 'Macro Reflexivity & Flows', desc: 'Macro regime shifts, feedback loops, and asymmetric trend capitalizing.' },
  { id: 'wyckoff', name: 'Richard Wyckoff', icon: '📈', style: 'VSA & Accumulation Springs', desc: 'Volume Spread Analysis, smart money accumulation, and effort vs result.' },
  { id: 'oneil', name: 'William O’Neil', icon: '📊', style: 'CAN SLIM Momentum', desc: 'Quarterly EPS acceleration, institutional sponsorship, and base breakouts.' },
  { id: 'smc', name: 'Smart Money (SMC / ICT)', icon: '🎯', style: 'Order Blocks & Liquidity', desc: 'Fractal CHoCH, unmitigated Demand/Supply blocks, and Fair Value Gaps.' },
  { id: 'simons', name: 'Jim Simons (Renaissance)', icon: '🔢', style: 'Statistical Arbitrage & Quant', desc: 'Mean reversion, volatility dispersion, and quantitative edges.' },
  { id: 'forensic', name: 'Forensic Auditor', icon: '🔍', style: 'Governance & Forensic Audit', desc: 'Beneish M-Score manipulation detection, Altman Z-Score, and promoter pledging.' },
]

export const QUANT_COMMANDS = [
  { cmd: 'analyze', label: 'AI Multi-Agent Synthesis', icon: '⚡', usage: 'analyze [SYMBOL]', desc: 'Full parallel bull/bear research & deep reasoning synthesis' },
  { cmd: 'brief', label: 'Morning Market Brief', icon: '🌅', usage: 'brief', desc: 'Macro posture, India VIX, NIFTY breadth & morning setups' },
  { cmd: 'radar', label: 'Top 10 High-Conviction Radar', icon: '🎯', usage: 'radar', desc: 'Algorithmic ranking across 500+ NSE liquid assets' },
  { cmd: 'structure', label: 'Market Structure & SMC', icon: '🏛️', usage: 'structure [SYMBOL]', desc: 'Order blocks, CHoCH reversals, VAH/VAL volume profile' },
  { cmd: 'multibagger', label: 'Minervini Stage 2 & VCP', icon: '💎', usage: 'multibagger [SYMBOL]', desc: '8-point Trend Template, VCP contractions, Stage 2 Markup' },
  { cmd: 'spreads', label: 'Defined-Risk Spread Builder', icon: '🛡️', usage: 'spreads [SYMBOL] [TYPE]', desc: 'Bull Call, Bear Put, Iron Condor with Max Gain & Loss' },
  { cmd: 'forensic', label: 'Forensic Accounting Audit', icon: '🔍', usage: 'forensic [SYMBOL]', desc: 'Beneish M-Score, Altman Z-Score & share pledging risk' },
  { cmd: 'whales', label: 'Marquee Whale & SAST Tracker', icon: '🐋', usage: 'whales', desc: 'Bulk/Block deals from Kacholia, Agrawal, Rare Enterprises' },
  { cmd: 'accuracy', label: 'Persona Accuracy Scoreboard', icon: '🏆', usage: 'accuracy', desc: 'Empirical win-rate matrix & dynamic calibrated weights' },
  { cmd: 'bigmove', label: 'Big Move Predictor', icon: '🚀', usage: 'bigmove [SYMBOL]', desc: 'Directional squeeze probability & imminent expansion' },
  { cmd: 'rrg', label: 'Sector Relative Rotation Graph', icon: '🌐', usage: 'rrg', desc: 'JdK RS-Ratio vs RS-Momentum sector momentum matrix' },
  { cmd: 'flows', label: 'FII / DII Institutional Flows', icon: '🌊', usage: 'flows', desc: 'Daily & 5-day cumulative institutional flows' },
  { cmd: 'funnel', label: 'Smart Funnel 4-Stage Screen', icon: '🎯', usage: 'funnel nifty_50', desc: 'Zero-token deterministic filter before LLM debate' },
  { cmd: 'lifecycle', label: 'Position Lifecycle & Trailing SL', icon: '📡', usage: 'lifecycle [SYM] [ENTRY] [SL]', desc: 'Active trade 2R breakeven & Chandelier ATR trailing stop' },
  { cmd: 'size', label: 'Volatility Risk-Parity Sizer', icon: '⚖️', usage: 'size [SYM] [ENTRY] [SL]', desc: 'Position sizing with F&O contract quantization' },
  { cmd: 'oi', label: 'Options Open Interest Profile', icon: '📊', usage: 'oi [SYMBOL]', desc: 'Call/Put build-up, PCR & Max Pain analysis' },
  { cmd: 'payoff', label: 'Option Strategy Payoff Curve', icon: '📈', usage: 'payoff [SYMBOL]', desc: 'Multi-leg Greeks and Breakeven payoff simulation' },
  { cmd: 'tax', label: 'Capital Gains Tax Estimator', icon: '🧾', usage: 'tax [GAIN] [DAYS]', desc: 'Indian STCG 20%, LTCG 12.5% and STT calculations' },
  { cmd: 'harvest', label: 'Tax-Loss Harvesting Scanner', icon: '🌾', usage: 'harvest', desc: 'Scan underwater holdings to offset taxable capital gains' },
  { cmd: 'scan', label: 'Live Market Momentum Heatmap', icon: '🔍', usage: 'scan', desc: 'Real-time NSE F&O gainers, losers and volume breakouts' },
]

// ── RECENT SEARCHES LOCALSTORAGE STORAGE ───────────────────────
const RECENT_KEY = 'chanakya_recent_searches_v1'

export function getRecentSearches() {
  try {
    const raw = typeof window !== 'undefined' ? window.localStorage?.getItem(RECENT_KEY) : null
    if (!raw) return []
    return JSON.parse(raw)
  } catch {
    return []
  }
}

export function saveRecentSearch(item) {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return
    const recents = getRecentSearches().filter((r) => r.text !== item.text && r.symbol !== item.symbol)
    recents.unshift({
      ...item,
      timestamp: Date.now(),
    })
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(recents.slice(0, 8)))
  } catch {
    // Ignore storage quota errors
  }
}

export function clearRecentSearches() {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.removeItem(RECENT_KEY)
    }
  } catch {}
}

// ── NORMALIZATION HELPER ──────────────────────────────────────
/**
 * Strips punctuation, hyphens, underscores, dots, and whitespace to match canonical keys
 * (e.g. 'bajaj-auto', 'bajaj_auto', 'bajaj auto', 'bajajauto' -> 'bajajauto').
 */
export function normalizeQuery(str) {
  if (!str) return ''
  return String(str).toLowerCase().replace(/[^a-z0-9]/g, '')
}

/**
 * Returns a suitable icon and category tag for an asset type
 */
export function getAssetIcon(type) {
  switch (type) {
    case 'index': return '📊'
    case 'etf': return '📦'
    case 'commodity': return '🪙'
    case 'currency': return '💱'
    case 'stock':
    default: return '🏢'
  }
}

// ── HIGH-PERFORMANCE FUZZY SEARCH MATCHING WITH CATEGORIES ────
export function fuzzySearchUniverse(query, activeSymbol = null, limit = 12, categoryFilter = 'all') {
  const rawClean = (query || '').trim().toLowerCase()
  const normQuery = normalizeQuery(rawClean)

  // 1. If query is empty, return category items if filtered, or Recent Searches + Top Actions if 'all'
  if (!rawClean) {
    if (categoryFilter === 'all') {
      const recents = getRecentSearches().map((r) => ({ ...r, category: 'recent' }))
      const defaultActions = [
        { type: 'command', text: activeSymbol ? `analyze ${activeSymbol}` : 'brief', label: activeSymbol ? `⚡ AI Multi-Agent (${activeSymbol})` : '🌅 Morning Market Brief', icon: '⚡', category: 'action' },
        { type: 'command', text: activeSymbol ? `council breakout ${activeSymbol}` : 'radar', label: activeSymbol ? `🚀 Breakout Council (${activeSymbol})` : '🎯 Top 10 High-Conviction Radar', icon: '🚀', category: 'action' },
        { type: 'command', text: activeSymbol ? `multibagger ${activeSymbol}` : 'whales', label: activeSymbol ? `💎 Minervini Stage 2 (${activeSymbol})` : '🐋 Marquee Whale Flows', icon: '💎', category: 'action' },
        { type: 'command', text: activeSymbol ? `forensic ${activeSymbol}` : 'flows', label: activeSymbol ? `🛡️ Forensic Audit (${activeSymbol})` : '🌊 FII / DII Institutional Flows', icon: '🛡️', category: 'action' },
        { type: 'command', text: activeSymbol ? `structure ${activeSymbol}` : 'accuracy', label: activeSymbol ? `🏛️ SMC Order Blocks (${activeSymbol})` : '🏆 AI Persona Accuracy Matrix', icon: '🏛️', category: 'action' },
      ]

      return [...recents, ...defaultActions].slice(0, limit)
    }

    if (['stock', 'index', 'etf', 'commodity', 'currency', 'symbols'].includes(categoryFilter)) {
      const filtered = INDIAN_UNIVERSE.filter((item) => {
        if (categoryFilter === 'symbols') return true
        return item.type === categoryFilter
      }).map((item) => ({
        type: 'symbol',
        symbol: item.symbol,
        name: item.name,
        sector: item.sector,
        subIndustry: item.subIndustry,
        stockType: item.type,
        capTier: item.capTier,
        lotSize: item.lotSize,
        isFO: item.isFO,
        category: item.type,
        icon: getAssetIcon(item.type),
        command: `analyze ${item.symbol}`,
        score: 100,
      }))
      return filtered.slice(0, limit)
    }

    if (categoryFilter === 'council') {
      const targetSym = activeSymbol || 'BAJAJ-AUTO'
      return COUNCIL_REGISTRY.map((c) => ({
        type: 'council',
        id: c.id,
        name: c.name,
        desc: c.desc,
        icon: c.icon,
        category: 'council',
        command: `council ${c.id} ${targetSym}`,
        label: `${c.name} (${targetSym})`,
        score: 100,
      })).slice(0, limit)
    }

    if (categoryFilter === 'persona') {
      const targetSym = activeSymbol || 'BAJAJ-AUTO'
      return PERSONA_REGISTRY.map((p) => ({
        type: 'persona',
        id: p.id,
        name: p.name,
        style: p.style,
        icon: p.icon,
        category: 'persona',
        command: `persona ${p.id} ${targetSym}`,
        label: `${p.name} • ${p.style}`,
        score: 100,
      })).slice(0, limit)
    }

    if (categoryFilter === 'command') {
      return QUANT_COMMANDS.map((cmd) => {
        let finalCmd = cmd.cmd
        if (cmd.usage.includes('[SYMBOL]')) {
          finalCmd = `${cmd.cmd} ${activeSymbol || 'BAJAJ-AUTO'}`
        }
        return {
          type: 'command',
          cmd: cmd.cmd,
          label: cmd.label,
          desc: cmd.desc,
          usage: cmd.usage,
          icon: cmd.icon,
          category: 'command',
          command: finalCmd,
          score: 100,
        }
      }).slice(0, limit)
    }
  }

  const results = []

  // 2. Search Symbols (Stocks, Indices, ETFs, Commodities, Currencies)
  if (categoryFilter === 'all' || ['stock', 'index', 'etf', 'commodity', 'currency', 'symbols'].includes(categoryFilter)) {
    for (const item of INDIAN_UNIVERSE) {
      if (categoryFilter !== 'all' && categoryFilter !== 'symbols' && item.type !== categoryFilter) {
        continue
      }

      const symLower = item.symbol.toLowerCase()
      const symNorm = normalizeQuery(item.symbol)
      const nameLower = item.name.toLowerCase()
      const sectorLower = (item.sector || '').toLowerCase()
      const subLower = (item.subIndustry || '').toLowerCase()
      const aliases = item.aliases || []

      // Scoring
      let score = 0

      // Exact symbol matches
      if (symLower === rawClean || symNorm === normQuery) {
        score = 200
      } else if (symLower.startsWith(rawClean) || symNorm.startsWith(normQuery)) {
        score = 120
      } else if (symLower.includes(rawClean) || symNorm.includes(normQuery)) {
        score = 90
      }

      // Exact Alias match
      if (!score) {
        for (const alias of aliases) {
          const aLower = alias.toLowerCase()
          const aNorm = normalizeQuery(alias)
          if (aLower === rawClean || aNorm === normQuery) {
            score = 150
            break
          } else if (aLower.startsWith(rawClean) || aNorm.startsWith(normQuery)) {
            score = 100
            break
          } else if (aLower.includes(rawClean) || aNorm.includes(normQuery)) {
            score = 70
            break
          }
        }
      }

      // Name / Sector / Sub-industry match
      if (!score) {
        if (nameLower.includes(rawClean)) {
          score = 50
        } else if (sectorLower.includes(rawClean) || subLower.includes(rawClean)) {
          score = 30
        }
      }

      if (score > 0) {
        results.push({
          type: 'symbol',
          symbol: item.symbol,
          name: item.name,
          sector: item.sector,
          subIndustry: item.subIndustry,
          stockType: item.type,
          capTier: item.capTier,
          lotSize: item.lotSize,
          isFO: item.isFO,
          category: item.type,
          icon: getAssetIcon(item.type),
          command: `analyze ${item.symbol}`,
          score,
        })
      }
    }
  }

  // 3. Search Councils
  if (categoryFilter === 'all' || categoryFilter === 'council') {
    for (const council of COUNCIL_REGISTRY) {
      const idMatch = council.id.toLowerCase().includes(rawClean) || council.id.replace(/_/g, '').includes(normQuery)
      const nameMatch = council.name.toLowerCase().includes(rawClean)
      const descMatch = council.desc.toLowerCase().includes(rawClean)

      if (idMatch || nameMatch || descMatch || rawClean.startsWith('counc')) {
        const targetSym = activeSymbol || 'BAJAJ-AUTO'
        results.push({
          type: 'council',
          id: council.id,
          name: council.name,
          desc: council.desc,
          icon: council.icon,
          category: 'council',
          command: `council ${council.id} ${targetSym}`,
          label: `${council.name} (${targetSym})`,
          score: idMatch ? 95 : 45,
        })
      }
    }
  }

  // 4. Search Personas
  if (categoryFilter === 'all' || categoryFilter === 'persona') {
    for (const persona of PERSONA_REGISTRY) {
      const idMatch = persona.id.toLowerCase().includes(rawClean)
      const nameMatch = persona.name.toLowerCase().includes(rawClean)
      const styleMatch = persona.style.toLowerCase().includes(rawClean)

      if (idMatch || nameMatch || styleMatch || rawClean.startsWith('pers')) {
        const targetSym = activeSymbol || 'BAJAJ-AUTO'
        results.push({
          type: 'persona',
          id: persona.id,
          name: persona.name,
          style: persona.style,
          icon: persona.icon,
          category: 'persona',
          command: `persona ${persona.id} ${targetSym}`,
          label: `${persona.name} • ${persona.style}`,
          score: idMatch ? 95 : 40,
        })
      }
    }
  }

  // 5. Search Quant Commands
  if (categoryFilter === 'all' || categoryFilter === 'command') {
    for (const cmd of QUANT_COMMANDS) {
      const cmdMatch = cmd.cmd.toLowerCase().includes(rawClean)
      const labelMatch = cmd.label.toLowerCase().includes(rawClean)
      const descMatch = cmd.desc.toLowerCase().includes(rawClean)

      if (cmdMatch || labelMatch || descMatch) {
        let finalCmd = cmd.cmd
        if (cmd.usage.includes('[SYMBOL]')) {
          finalCmd = `${cmd.cmd} ${activeSymbol || 'BAJAJ-AUTO'}`
        }
        results.push({
          type: 'command',
          cmd: cmd.cmd,
          label: cmd.label,
          desc: cmd.desc,
          usage: cmd.usage,
          icon: cmd.icon,
          category: 'command',
          command: finalCmd,
          score: cmdMatch ? 85 : 35,
        })
      }
    }
  }

  // Sort by score descending and return top matches
  results.sort((a, b) => b.score - a.score)
  return results.slice(0, limit)
}
